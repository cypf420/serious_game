import json
import shutil

import pytest
from tools import build_story_integrity_candidate as builder

def test_pinned_baseline_rejects_modified_snapshot(tmp_path,monkeypatch):
    shutil.copytree(builder.BASELINE/'baseline-package',tmp_path/'baseline-package')
    shutil.copyfile(builder.BASELINE/'baseline-authority.json',tmp_path/'baseline-authority.json')
    monkeypatch.setattr(builder,'BASELINE',tmp_path)
    builder.verify_baseline()
    target=tmp_path/'baseline-package/decisions.json'
    target.write_bytes(target.read_bytes()+b' ')
    with pytest.raises(ValueError,match='fingerprint'): builder.verify_baseline()

@pytest.mark.parametrize('drift',['extra-file','registry','authority','package'])
def test_install_preflight_rejects_drift_without_changing_files(tmp_path,drift):
    package=tmp_path/'package'; package.mkdir()
    (package/'decisions.json').write_text('{}')
    hashes=builder.file_hashes(package)
    auth=tmp_path/'authority'; auth.write_text('authority')
    previous_auth=tmp_path/'previous-authority'; previous_auth.write_text('authority')
    reg=tmp_path/'registry'; reg.write_text('registry')
    previous_reg=tmp_path/'previous-registry'; previous_reg.write_text('registry')
    if drift=='extra-file': (package/'extra.md').write_text('user addition')
    elif drift=='registry': reg.write_text('user edit')
    elif drift=='authority': auth.write_text('user edit')
    else: (package/'decisions.json').write_text('{"edit":1}')
    before={p.name:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError,match='drift'):
        builder.verify_install_target(package,hashes,auth,previous_auth,reg,previous_reg)
    assert before=={p.name:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
