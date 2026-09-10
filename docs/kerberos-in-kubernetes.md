# Giving the connector a Kerberos ticket in Kubernetes

A plan for reaching SSAS with a domain identity from the OpenMetadata ingestion pods, modelled
on the krb5 sidecar already running in the Airflow platform.

**Short answer: the sidecar cannot be lifted across as-is, and the reason is not the sidecar.**
Two independent blockers sit in front of it, one of which would stop *any* Kerberos route. Both
are fixable; neither is obvious from the outside. There is also a route that needs no Kerberos
at all and is the only one verified end to end today.

## What the Airflow platform actually does

Worth being precise, because there are two patterns in that repo and only the newer one is
live. `images/dbt-runtime/krb5-renew.sh` is an **entrypoint wrapper** — `kinit`, a background
renew loop, then `exec "$@"`. It has been **replaced**, and the file's own successor says so:
`pod-templates/dbt-kpo.yaml` runs a **native sidecar** instead.

```yaml
initContainers:
  - name: krb5-sidecar
    image: <registry>/krb-kinit:latest
    restartPolicy: Always          # <- this is what makes it a sidecar, not an init container
    env:
      - {name: KRB5_PRINCIPAL, valueFrom: {secretKeyRef: {name: ...-mssql-keytab, key: username}}}
      - {name: KRB5_KEYTAB,    value: /keytab/krb5.keytab}
      - {name: KRB5CCNAME,     value: "FILE:/tmp/krb/krb5cc_cache"}
      - {name: REFRESH_INTERVAL, value: "1800"}
    volumeMounts:
      - {name: krb5-cache, mountPath: /tmp/krb}          # emptyDir, shared
      - {name: mssql-keytab, mountPath: /keytab, readOnly: true}
```

The consuming container then sets `KRB5CCNAME` to the same path and mounts `krb5-cache`
read-only. Four properties of that design matter for us:

| property | why it matters here |
|---|---|
| `restartPolicy: Always` on an init container | native sidecars are **K8s ≥ 1.29**; below that this either fails admission or runs once with no refresh |
| `runAsUser: 50000` on **both** containers | `kinit` writes the ccache 0600, so the consumer must be the same uid or it cannot read its own ticket |
| keytab Secret at `defaultMode: 0440`, not 0400 | secret files are root-owned; a non-root container reads them only via the group bit plus `fsGroup` |
| an **emptyDir** carries the ccache | this is the part the OMJob CRD cannot express — see below |

## Blocker 1 — the OMJob CRD cannot express a sidecar

Ingestion here is not Airflow. It runs through the bundled **`omjob-operator`**, which
reconciles `OMJob` custom resources and spawns one Job pod per pipeline. The pod's shape comes
entirely from `OMJob.spec.mainPodSpec`, and that schema
(`charts/2.0.1/openmetadata/templates/omjob-crd.yaml`) offers exactly:

```
image  imagePullPolicy  imagePullSecrets  serviceAccountName  command  env
resources  nodeSelector  tolerations  securityContext  labels  annotations
```

There is **no `volumes`, no `volumeMounts`, no `initContainers`, no `extraContainers`**. So the
sidecar, the shared `emptyDir` ccache, the keytab Secret and the `krb5.conf` ConfigMap have no
field to go in. `omjobOperator.podSecurityContext` in `values-psa-restricted.yaml` does not
help: it hardens the **operator's own Deployment**, not the pods it spawns.

This is a schema gap, not a policy — which is why it can be worked around from outside.

## Blocker 2 — the ingestion image cannot do Kerberos at all

This one would stop every route above, and nothing about the image advertises it. Measured
inside `openmetadata/ingestion:2.0.1.0`:

| probe | result |
|---|---|
| `kinit`, `klist` | **present** (`/usr/bin/kinit`) |
| `libkrb5` | **present** (6 entries in `ldconfig -p`) |
| `spnego` | **present** |
| `import gssapi` | **`ModuleNotFoundError`** |
| `spnego.client(..., protocol="kerberos")` | **`ImportError: GSSAPIProxy requires the Python gssapi library`** |
| `spnego.client(..., protocol="ntlm")` | works |

So the image can *obtain* a ticket (`kinit` runs, libkrb5 is there) but the connector cannot
*use* one: on Linux `pyspnego` reaches Kerberos only through python-`gssapi`, which is absent.

A trap worth recording: `spnego`'s `GSSAPIProxy.available_protocols()` returns `['kerberos']`
in this image regardless. It reports a static capability list, not what is actually importable.
Do not use it as a readiness check — create a context instead.

**Fix:** a derived image with `pip install gssapi` (or `pyspnego[kerberos]`). `libkrb5` is
already there, but the build needs `krb5-config` and the dev headers, so this is a build-stage
dependency, not a one-line `pip install` in the final layer. This is required for *any*
Kerberos option below and should be proven first, because it is cheap to test and everything
else depends on it.

## Routes

### A. Kyverno mutating policy — recommended, if Kerberos is required

Both platform repos already run Kyverno, currently for validation only
(`kyverno/psa-restricted.yaml`). A `mutate` rule is the standard way to inject into pods whose
spec you do not control, and it fits unusually well here because the CRD **does** expose
`labels` and `annotations` on `mainPodSpec` — so the OMJob can carry a precise, intentional
marker to match on, rather than the policy pattern-matching the operator's naming.

Shape:

1. The SSAS pipeline's OMJob sets `mainPodSpec.labels: {ssas-kerberos: "true"}`.
2. A Kyverno `ClusterPolicy` matching pods with that label in the OpenMetadata namespace adds:
   the `krb5-sidecar` init container with `restartPolicy: Always`; the `krb5-cache` emptyDir;
   the keytab Secret and `krb5.conf` ConfigMap volumes; the matching `volumeMounts`; and
   `KRB5CCNAME` / `KRB5_CONFIG` on the main container.
3. The OMJob sets `securityContext` so the main container's uid matches the sidecar's, or the
   0600 ccache is unreadable.

Verify in this order, stopping at the first failure:

- the policy mutates at all — `kubectl get pod -o yaml` on a spawned Job pod shows the sidecar
- `klist` inside the main container shows a ticket for the expected principal
- the SPN the connector asks for matches how the instance is registered (see below)
- a real ingestion run completes

Risks: the mutation is invisible in the OMJob, so a failure looks like an operator bug —
document it where the pipeline is defined, not only in the policy. And a Kyverno policy that
silently stops matching (a renamed label) degrades to "no ticket", which surfaces as an
authentication error pointing at the wrong cause.

### B. Derived image with a kinit entrypoint — blocked, and worth knowing why

The CRD exposes `command` and `env`, so the old `krb5-renew.sh` pattern looks viable without
touching the pod shape. It is not: the keytab still has to reach the container, and with no
`volumes` field the only remaining channel is an env var — which means a base64 keytab in the
OMJob spec. That is a credential in a CR, readable by anyone with `get omjob`. Do not.

### C. No Kerberos — `authMechanism: ntlm`

The connector reaches SSAS over the native TCP binding with NTLM using `user` and `password`
from `connectionOptions`. No ticket, no sidecar, no volumes, no CRD gap, and no image change —
`spnego`'s NTLM path works in the stock image today.

**This is the only path verified end to end**: `test_connection()`, catalogs, 127 tables and
1366 columns, run through the real ingestion image against a live SQL Server 2022 instance.

The cost is real and should be stated rather than glossed: `connectionOptions` is a plain
string map in the OpenMetadata schema with no password format, so the password is stored as an
ordinary option value without the masking and secret-manager handling a built-in connector's
password field receives.

Recommendation: **do this first regardless.** It gets ingestion working while the Kerberos
route is built, and it is the fallback if route A stalls.

### D. Close the CRD gap upstream

Add `volumes` / `volumeMounts` / `initContainers` to `mainPodSpec`. The right long-term fix and
the only one that makes this configuration rather than infrastructure trickery — but it is an
upstream change on someone else's release cycle, so it cannot be the plan for this quarter.

## Two things that will bite regardless of route

**The SPN must match how the instance is registered.** NTLM ignores the target, so a wrong SPN
is invisible until the first Kerberos attempt. `Credential.target()` asks for
`MSOLAPSvc.3/<host>` by default; ADOMD's `CalculateNTAuthenticationSPN` asks for
`MSOLAPSvc.3/<host>:<port>` (or `:<instance>` for a named instance) — but that form is only
justified on Windows SSPI. On the GSSAPI path used here the host half is imported as
`hostbased_service` and goes through krb5 realm determination, where a trailing `example:2383`
resolves to no realm. The port and instance forms are therefore **opt-in**
(`use_port=True`, `instance=`, or a full `spn=`), and `python -m ssas_xmla.probe` exposes all
three plus prints which SPN it requested when authentication fails.

**Kerberos has never been exercised against a real KDC.** The framing is mechanism-agnostic per
the ADOMD decompile, and the code fails closed on a padding mechanism rather than corrupting
the request, but the test fixture is a standalone workgroup machine whose SSAS speaks NTLM
only. The first genuine Kerberos test will be against production. Budget for that being where
the SPN and realm problems surface.

## Suggested order

1. **Prove route C** end to end in the target cluster. Unblocks ingestion now; no image or
   platform change.
2. **Build the derived ingestion image with `gssapi`** and prove `spnego.client(protocol=
   "kerberos")` constructs. Cheap, and blocker 2 defeats every Kerberos route until it is done.
3. **Check the cluster is K8s ≥ 1.29**, or native sidecars are not available and the whole
   sidecar design has to change.
4. **Write the Kyverno mutating policy** against a hand-written OMJob before wiring it to a
   real pipeline, so mutation failures are diagnosed in isolation.
5. **Confirm the SPN** with the AD team — registered form and the account's realm — before the
   first live attempt, not after.
