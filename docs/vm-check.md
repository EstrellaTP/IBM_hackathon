# LinuxONE VM check

What the LinuxONE Community Cloud VM offers, what had to be installed, and what
fails on s390x with its workaround. Raw transcript for the jury:
[`docs/screenshots/vm_check.txt`](screenshots/vm_check.txt), regenerated with:

```bash
scripts/sync_to_vm.sh                                   # copy the repo (no secrets, no data)
ssh l1cc 'bash -s' < scripts/vm_check.sh > docs/screenshots/vm_check.txt
```

## 1. Machine (checked 2026-10-18, task F0-BE-01)

| Item | Value | Why it matters |
|---|---|---|
| Architecture | `s390x`, **Big Endian** | Binary formats must fix byte order; compare laptop vs VM predictions |
| Machine type | `9175` = **IBM z17** (Telum II processor), 5.5 GHz | Latest IBM Z generation |
| Hypervisor | z/VM 7.3.0 | |
| CPU facilities | `nnpa` present (also `vx`, `vxe2`, `vxp2`, `sort`, `dflt`, `msa`) | Integrated Accelerator for AI available |
| NNPA usable from the guest | **yes** (zDNN 1.0.1: `nnpa_installed=yes`, `NNPA_MATMUL_OP=yes`, `NNPA_ADD=yes`) | Real accelerator comparison possible (task F3-BE-02) |
| vCPUs / RAM / swap | 3 / 7.8 GiB / none | Training on NHANES must stream `PAXMIN` in chunks |
| Disk | 50 GB, 44 GB free | Enough for WESAD (~2 GB), DEPRESJON, NHANES cycle H |
| OS / kernel | Ubuntu 24.04.5 LTS, Linux 6.8.0-147 | |
| Python (host) | 3.12.3 | |
| Docker | **not preinstalled**; installed `docker.io` 29.1.3 + `docker-compose-v2` 2.40.3 from Ubuntu | CLAUDE.md §6 assumed it was preinstalled |
| Official images | `python:3.12-slim` pulls the `linux/s390x` variant and reports `s390x big` | Multi-arch images work as-is |
| sudo | passwordless for `linux1` | |
| Public IP | `148.100.99.58` (interface `enc1000`) | |

## 2. Security features

| Feature | Status | Use in the project |
|---|---|---|
| **CPACF** (on-chip crypto, MSA 9) | Present. `icainfo`: AES-CBC/GCM/XTS, SHA-2/SHA-3, GHASH, ECDSA, Ed25519, X25519 **in hardware** (static) | Fernet (AES-128-CBC + HMAC-SHA256) for encryption at rest and TLS 1.3 (X25519 + AES-GCM) run on CPACF. Kernel modules `aes_s390`, `sha256_s390`, `ghash_s390`, `pkey` loaded |
| Crypto Express cards (HSM) | None (`lszcrypt: No crypto card devices found`) | No secure-key (HSM-held) keys; keys live in `.env` on the VM |
| Secure Execution | **Not enabled** (no `/sys/firmware/uv`) | Must be stated honestly: the datathon VM is a demo environment, not the production deployment (CLAUDE.md §11) |
| Inbound firewall | `iptables` in the guest: `INPUT` accepts only 22/tcp, ICMP and established; everything else `REJECT` | See F0-BE-05 for opening the demo ports |

## 3. Installed on the VM

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 python3-pip python3-venv python3-dev \
    build-essential cmake git tmux libzdnn0 libzdnn-dev libica-utils
sudo usermod -aG docker linux1   # new SSH sessions can run docker without sudo
sudo systemctl enable --now docker
```

## 4. Python libraries on s390x (task F0-BE-02)

**Result: the whole stack installs and works on s390x. No plan B is needed** (LightGBM
and SHAP included). Functional evidence, not just imports:
[`docs/screenshots/vm_python_stack.txt`](screenshots/vm_python_stack.txt)
(`tools/vm_check/stack_check.py`: fits logistic regression, Random Forest and LightGBM,
checks SHAP additivity, Fernet round trip and a FastAPI request on big-endian s390x).

PyPI has **no s390x wheels** for the scientific packages: pip compiles them from
source. Times on the VM (3 vCPUs, z17), Python 3.12 venv `~/venv-holter`:

| Package | Version | Result | Time | Notes |
|---|---|---|---|---|
| numpy | 2.5.4 | OK, source build | 140 s | Built before OpenBLAS was installed, so it uses its internal fallback (`BLAS: auto`) |
| pandas | 3.0.6 | OK, source build | 176 s | |
| scikit-learn | 1.9.1 | **failed**, then OK | — | 1st try: scipy (build dependency) needs a Fortran compiler: `ERROR: Unknown compiler(s): [['gfortran'], ...]`. Fixed by `apt install gfortran libopenblas-dev liblapack-dev pkg-config` |
| scipy | 1.18.1 | OK, source build | (inside lightgbm) | Needs gfortran + OpenBLAS |
| lightgbm | 4.7.0 | OK, source build | 607 s | Most of the time is scipy; LightGBM itself builds with cmake |
| shap | 0.54.1 | OK, source build | 128 s | No numba/llvmlite dependency in this version |
| cryptography | 50.0.2 | **failed**, then OK | 64 s | 1st try: `openssl-sys ... Could not find directory of OpenSSL installation`. Fixed by `apt install libssl-dev pkg-config`; Rust is fetched automatically by the build backend. Links the system OpenSSL 3.0.13 (CPACF-accelerated AES/SHA) |
| fastapi | 0.143.3 | OK, pure Python | 3 s | |
| uvicorn[standard] | 0.54.0 | OK | 78 s | `uvloop`, `httptools`, `watchfiles` compiled |
| pydantic | 2.14.1 | OK | — | `pydantic-core` has an s390x wheel |

Build dependencies needed on the host (and in any Docker build stage):

```bash
sudo apt-get install -y build-essential cmake gfortran libopenblas-dev liblapack-dev \
    pkg-config libssl-dev python3-dev
```

Implications for the Docker images (F0-BE-03/04):
- Building from source in every `docker build` costs ~20 minutes. Use a **multi-stage
  build**: a builder stage with the packages above runs `pip wheel` once (cached by
  Docker), the runtime stage installs the wheels plus only `libopenblas0`/`libgomp1`.
- Install OpenBLAS **before** numpy in the builder so numpy links an optimised BLAS
  (OpenBLAS has kernels for the z vector facility).
- Reproduce exact versions with the pins above (`ml/requirements.txt`).

## 5. Inbound ports (task F0-BE-05)

**Result: inbound ports can be opened; the only firewall is `iptables` inside the guest.**
No plan B (SSH tunnel) is needed.

Test (2026-10-18), from the laptop on a home ISP connection, i.e. from the public
internet outside Marist's network:

| Step | 443 | 8080 | 8443 | 9443 (Docker `-p`) | 5555 (nothing) |
|---|---|---|---|---|---|
| `python3 -m http.server` on the host, default guest firewall | timeout | timeout | timeout | | |
| Same, after `iptables -I INPUT -p tcp --dport <port> ... -j ACCEPT` | **200** | **200** | **200** | | timeout |
| `docker run -p 9443:80 nginx:alpine`, **no** INPUT rule | | | | **200** | |

Findings:
- The guest rule set ends in `REJECT --reject-with icmp-host-prohibited`; from outside it
  looks like a timeout because the ICMP reply is filtered on the way. There is no
  upstream (cloud) firewall in front of the VM for these ports.
- **Ports published by Docker bypass the `INPUT` chain** (Docker DNATs them in
  `PREROUTING` and they traverse `FORWARD`, whose policy is `ACCEPT`). Any port mapped
  with `ports:` in `docker compose` is reachable from the internet. Therefore the compose
  file must publish **only** the HTTPS entry point; internal services stay on the
  compose network without `ports:` (or bind to `127.0.0.1:`).
- Persistent rules: 443/tcp and 8443/tcp were added to `/etc/iptables/rules.v4`
  (loaded at boot by `netfilter-persistent`; backup `rules.v4.bak-YYYYMMDD`). The file
  was edited by hand instead of running `netfilter-persistent save`, which would also
  persist Docker's own chains and clash with them at boot.
- Demo entry point: **`https://148.100.99.58:8443`** (TLS, self-signed is acceptable,
  task F1-BE-05). Port 8080 was closed again after the test.
- Still to do by a person: open the demo URL on a phone **on mobile data** once
  F1-BE-05 is deployed (part of F1-HUM-01). The laptop test already shows the VM is
  reachable from an arbitrary internet connection.

## 6. Gotchas

- `ssh l1cc "<cmd>"` only; never interactive sessions from the agent.
- The repository is private, so the VM has no GitHub credentials: code is copied with
  `scripts/sync_to_vm.sh` (git-tracked files only).
- Commits from Windows: `.gitattributes` forces LF, otherwise shell scripts arrive
  with CRLF and fail in bash on the VM.
