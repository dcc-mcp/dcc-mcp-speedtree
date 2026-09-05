from dcc_mcp_speedtree.content import discover_official_content, select_samples

def test_select_samples(tmp_path):
    (tmp_path/'samples'/'A').mkdir(parents=True); (tmp_path/'export_presets'/'Games').mkdir(parents=True)
    for name in ('Pine.spm','Broadleaf_Forest.spm','Palm.spm'): (tmp_path/'samples'/name).write_text('x')
    (tmp_path/'export_presets'/'Games'/'__UnrealEngine (ST).ini').write_text('x')
    content=discover_official_content(tmp_path)
    assert len(select_samples(content)) == 3
    assert content['game_export_presets']
