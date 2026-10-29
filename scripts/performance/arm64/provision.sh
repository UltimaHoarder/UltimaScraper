#!/bin/bash
set -euo pipefail
mountpoint -q /srv/usr
export TMPDIR=/srv/usr/tmp
export UV_CACHE_DIR=/srv/usr/cache/uv
export PIP_CACHE_DIR=/srv/usr/cache/pip
export XDG_CACHE_HOME=/srv/usr/cache
export UV_PYTHON_DOWNLOADS=never
if ! test -f /srv/usr/packages.complete; then
  sudo install -d /etc/postgresql-common
  printf 'create_main_cluster = false\n' | sudo tee /etc/postgresql-common/createcluster.conf >/dev/null
  sudo apt-get update -qq
  sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get install -y --no-install-recommends postgresql redis-server python3-venv python3-dev build-essential libffi-dev pkg-config git ca-certificates ffmpeg
  sudo systemctl disable --now postgresql.service redis-server.service
  sudo swapoff -a
  python3 -m venv /srv/usr/bootstrap
  /srv/usr/bootstrap/bin/pip install --disable-pip-version-check uv==0.12.10
  touch /srv/usr/packages.complete
fi
python3 - <<'PY'
import json
from pathlib import Path
root=Path('/srv/usr/project')
expected=set(json.loads(Path('/srv/usr/source-manifest.json').read_text())['files'])
for path in root.rglob('*.py'):
    relative=path.relative_to(root)
    if '.venv' not in relative.parts and str(relative) not in expected:
        path.unlink()
PY
tar -xzf /srv/usr/source.tar.gz -C /srv/usr/project
cd /srv/usr/project/UltimaScraper
/srv/usr/bootstrap/bin/uv sync --locked --no-dev --python /usr/bin/python3.14
.venv/bin/python - <<'PY'
import json, platform
from pathlib import Path
from importlib.metadata import version
memory={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.endswith('kB')}
data={'architecture':platform.machine(),'python':platform.python_version(),'kernel':platform.release(),'memory_total_bytes':memory['MemTotal'],'swap_total_bytes':memory['SwapTotal'],'packages':{name:version(name) for name in ['psutil','SQLAlchemy','redis','ultima-scraper-backend','ultima-scraper-api']}}
Path('/srv/usr/environment.json').write_text(json.dumps(data,indent=2)+'\n')
manifest=json.loads(Path('/srv/usr/source-manifest.json').read_text())
import hashlib
for relative, expected in manifest['files'].items():
    assert hashlib.sha256((Path('/srv/usr/project')/relative).read_bytes()).hexdigest()==expected, relative
PY
