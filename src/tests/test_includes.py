import io

import pytest

from configobj import ConfigObj, ConfigObjError, Section
from configobj.validate import Validator


def write_file(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as stream:
        stream.write(content)
    return path


def test_include_is_ordinary_data_by_default(tmp_path):
    filename = write_file(tmp_path, 'root.ini', 'include = missing.ini\nkey = local\n')
    config = ConfigObj(filename)
    assert config['include'] == 'missing.ini'
    assert config.included_files == ()


def test_sorted_globs_local_precedence_and_nested_merge(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = conf.d/*.ini\nkey = local\n[devices]\n[[alpha]]\nport = 3000\n')
    first = write_file(tmp_path, 'conf.d/10.ini', 'key = first\nchoice = first\n[devices]\n[[alpha]]\nport = 1000\nname = alpha\n')
    second = write_file(tmp_path, 'conf.d/20.ini', 'choice = second\n[devices]\n[[beta]]\nport = 2000\n')
    config = ConfigObj(root, include_key='include')
    assert config.dict() == {'key': 'local', 'choice': 'second', 'devices': {
        'alpha': {'port': '3000', 'name': 'alpha'}, 'beta': {'port': '2000'}}}
    assert config.included_files == (str(first), str(second))
    assert 'include' not in config


def test_list_order_and_relative_nested_includes(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = dir/child.ini, last.ini\n')
    write_file(tmp_path, 'dir/child.ini', 'include = deeper/base.ini\nvalue = child\n')
    write_file(tmp_path, 'dir/deeper/base.ini', 'value = base\nshared = nested\n')
    write_file(tmp_path, 'last.ini', 'value = last\n')
    config = ConfigObj(root, include_key='include')
    assert config.dict() == {'value': 'last', 'shared': 'nested'}
    assert len(config.included_files) == 3


@pytest.mark.parametrize('files', [
    {'root.ini': 'include = root.ini\n'},
    {'root.ini': 'include = child.ini\n', 'child.ini': 'include = root.ini\n'},
])
def test_cycles_name_the_full_chain(tmp_path, files):
    for name, content in files.items():
        write_file(tmp_path, name, content)
    with pytest.raises(ConfigObjError, match='Recursive config include:') as caught:
        ConfigObj(tmp_path / 'root.ini', include_key='include')
    assert str(caught.value).count('root.ini') >= 2


def test_symlink_alias_cannot_hide_a_cycle(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = alias.ini\n')
    alias = tmp_path / 'alias.ini'
    try:
        alias.symlink_to('root.ini')
    except OSError as error:
        pytest.skip('Symlinks unavailable: ' + str(error))
    with pytest.raises(ConfigObjError, match='Recursive config include:'):
        ConfigObj(root, include_key='include')


def test_missing_literal_fails_but_empty_glob_is_allowed(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = conf.d/*.ini\nkey = local\n')
    assert ConfigObj(root, include_key='include').dict() == {'key': 'local'}
    root.write_text('include = missing.ini\n', encoding='utf-8')
    with pytest.raises(IOError, match='missing.ini'):
        ConfigObj(root, include_key='include')
    assert not (tmp_path / 'missing.ini').exists()


def test_anonymous_sources_require_explicit_directory(tmp_path):
    write_file(tmp_path, 'child.ini', 'key = included\n')
    with pytest.raises(ConfigObjError, match='include_base_dir'):
        ConfigObj(['include = child.ini'], include_key='include')
    for source in (['include = child.ini'], io.BytesIO(b'include = child.ini'), {'include': 'child.ini'}):
        config = ConfigObj(source, include_key='include', include_base_dir=tmp_path)
        assert config['key'] == 'included'


def test_comments_and_section_ownership(tmp_path):
    root = write_file(tmp_path, 'root.ini', '# root header\ninclude = child.ini\n# local comment\nkey = local # inline\n')
    write_file(tmp_path, 'child.ini', '# child header\nkey = child\n[section] # section note\n'
               '# value note\nvalue = yes # value inline\n')
    config = ConfigObj(root, include_key='include')
    assert config.initial_comment == ['# root header']
    assert config.comments['key'] == ['# local comment']
    assert config.inline_comments['key'] == '# inline'
    section = config['section']
    assert section.parent is config and section.main is config
    assert config.inline_comments['section'] == '# section note'
    assert section.comments['value'] == ['# value note']
    assert section.inline_comments['value'] == '# value inline'


def test_interpolation_waits_for_complete_merged_tree(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = child.ini\nroot = /srv\npath = %(shared)s/data\n')
    write_file(tmp_path, 'child.ini', 'shared = %(root)s/shared\n[section]\nvalue = %(root)s/nested\n')
    config = ConfigObj(root, include_key='include')
    assert config['path'] == '/srv/shared/data'
    assert config['section']['value'] == '/srv/nested'


def test_validation_runs_on_the_combined_configuration(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = child.ini\nname = service\n')
    write_file(tmp_path, 'child.ini', 'port = 9000\n[server]\ntls = true\n')
    spec = ['name = string', 'port = integer', '[server]', 'tls = boolean']
    config = ConfigObj(root, include_key='include', configspec=spec)
    assert config.validate(Validator()) is True
    assert config['port'] == 9000
    assert config['server']['tls'] is True
    assert config.extra_values == []


def test_scalar_section_replacement_keeps_membership_consistent(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = child.ini\nto_scalar = local\n[to_section]\nvalue = local\n')
    write_file(tmp_path, 'child.ini', 'to_section = child\n[to_scalar]\nvalue = child\n')
    config = ConfigObj(root, include_key='include')
    assert config.scalars == ['to_scalar']
    assert config.sections == ['to_section']
    assert config['to_scalar'] == 'local'
    assert isinstance(config['to_section'], Section)
    config.filename = None
    assert ConfigObj(config.write()) == config


def test_write_materializes_output_without_changing_included_files(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = child.ini\nlocal = root\n')
    child = write_file(tmp_path, 'child.ini', 'value = child\n')
    original = child.read_bytes()
    config = ConfigObj(root, include_key='include')
    config['value'] = 'edited'
    config.write()
    assert child.read_bytes() == original
    assert 'include' not in root.read_text(encoding='utf-8')
    assert ConfigObj(root, include_key='include').dict() == {'value': 'edited', 'local': 'root'}


def test_reload_refreshes_included_files_and_reset_disables_expansion(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = child.ini\n')
    child = write_file(tmp_path, 'child.ini', 'value = first\n')
    config = ConfigObj(root, include_key='include')
    child.write_text('value = second\n', encoding='utf-8')
    config.reload()
    assert config['value'] == 'second'
    assert config.include_key == 'include'
    assert config.included_files == (str(child),)
    config.reset()
    assert config.include_key is None and config.included_files == ()


def test_literal_brackets_and_unicode_paths(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = "d\u00e9vice[1].ini"\n')
    write_file(tmp_path, 'd\u00e9vice[1].ini', 'value = \u96ea\n')
    assert ConfigObj(root, include_key='include', encoding='utf-8')['value'] == '\u96ea'


def test_malformed_included_file_reports_its_path(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = child.ini\n')
    write_file(tmp_path, 'child.ini', 'not valid configuration\n')
    with pytest.raises(ConfigObjError, match='Cannot include .*child.ini') as caught:
        ConfigObj(root, include_key='include')
    assert isinstance(caught.value.__cause__, ConfigObjError)


def test_custom_directive_name_and_nested_data_key(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'sources = child.ini\n[section]\nsources = ordinary data\n')
    write_file(tmp_path, 'child.ini', 'value = included\n')
    config = ConfigObj(root, include_key='sources')
    assert config['value'] == 'included'
    assert config['section']['sources'] == 'ordinary data'


def test_repeated_noncyclic_inclusion_is_allowed(tmp_path):
    root = write_file(tmp_path, 'root.ini', 'include = a.ini, b.ini\n')
    write_file(tmp_path, 'a.ini', 'include = shared.ini\na = yes\n')
    write_file(tmp_path, 'b.ini', 'include = shared.ini\nb = yes\n')
    write_file(tmp_path, 'shared.ini', 'shared = yes\n')
    config = ConfigObj(root, include_key='include')
    assert config.dict() == {'shared': 'yes', 'a': 'yes', 'b': 'yes'}


def test_unrepr_dict_values_stay_scalars(tmp_path):
    root = write_file(tmp_path, 'root.ini', "include = 'child.ini'\n")
    write_file(tmp_path, 'child.ini', "value = {'one': 1}\n")
    config = ConfigObj(root, include_key='include', unrepr=True)
    assert config['value'] == {'one': 1}
    assert 'value' in config.scalars and not config.sections


def test_configspecs_never_expand_directives():
    config = ConfigObj(['include = string'], _inspec=True, include_key='include')
    assert config['include'] == 'string'


@pytest.mark.parametrize('value', [42, ['child.ini', 42], {'nested': 'section'}])
def test_invalid_directive_values_are_rejected(value, tmp_path):
    with pytest.raises(ConfigObjError, match='include directive'):
        ConfigObj({'include': value}, include_key='include', include_base_dir=tmp_path)


def test_empty_directive_and_absolute_path(tmp_path):
    assert ConfigObj(['include ='], include_key='include').dict() == {}
    child = write_file(tmp_path, 'child.ini', 'value = absolute\n')
    config = ConfigObj({'include': str(child)}, include_key='include')
    assert config['value'] == 'absolute'
