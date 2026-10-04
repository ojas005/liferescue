# packages/

**Purpose:** shared libraries used by more than one app/service/agent (for example shared schemas and clients).

**Source:** directory skeleton from doc 19 Step 2. The baseline does not define the contents of this directory; the purpose above is an interpretation and the layout is **TBD**.

**Status:** contains [`secrets/`](secrets/README.md), the mock-only KAN-45 secret-management slice. [`contract/`](contract/CONTRACT-README.md) is the platform contract 0.1.0 (KAN-19; schemas, run state machine, ports, OpenAPI, test fakes; proposed, see its README). Other packages: none yet.
