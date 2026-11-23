"""Expand opt-in root include directives into one owned configuration tree."""

import copy
import glob
import os


def expand_includes(config):
    """Merge included files in order, then apply the containing file last."""
    from . import ConfigObj, ConfigObjError, OPTION_DEFAULTS, Section

    key = config.include_key
    if not isinstance(key, str) or not key:
        raise TypeError('include_key must be a non-empty string or None')
    options = {name: getattr(config, name) for name in OPTION_DEFAULTS}
    options.update(configspec=None, include_key=None, include_base_dir=None,
                   file_error=True, create_empty=False)

    def merge(target, source, skip=None):
        # Bypass interpolation until the entire tree exists: an included value
        # may refer to a key supplied by its containing file (or vice versa).
        for name in source.scalars + source.sections:
            if name == skip:
                continue
            value = dict.__getitem__(source, name)
            existing = dict.get(target, name)
            if name in target and isinstance(existing, Section) != isinstance(value, Section):
                del target[name]
            if isinstance(value, Section):
                if name not in target:
                    target[name] = {}
                merge(dict.__getitem__(target, name), value)
            else:
                target.__setitem__(name, copy.deepcopy(value), unrepr=True)
            target.comments[name] = list(source.comments.get(name, []))
            target.inline_comments[name] = source.inline_comments.get(name, '')

    def expand(current, chain):
        filename = os.path.abspath(current.filename) if current.filename else None
        identity = os.path.normcase(os.path.realpath(filename)) if filename else None
        if identity is not None:
            if identity in [item[0] for item in chain]:
                paths = [item[1] for item in chain] + [filename]
                raise ConfigObjError('Recursive config include: ' + ' -> '.join(paths))
            chain = chain + [(identity, filename)]
        if key not in current:
            return []
        if key in current.sections:
            raise ConfigObjError('The include directive %r must be a scalar or list' % key)
        patterns = dict.__getitem__(current, key)
        if isinstance(patterns, str):
            patterns = [patterns] if patterns else []
        if not isinstance(patterns, (list, tuple)) or not all(isinstance(item, str) for item in patterns):
            raise ConfigObjError('The include directive %r must contain path strings' % key)
        if filename:
            base = os.path.dirname(filename)
        elif config.include_base_dir is not None:
            base = os.path.abspath(os.fspath(config.include_base_dir))
        elif any(pattern and not os.path.isabs(os.path.expanduser(pattern)) for pattern in patterns):
            raise ConfigObjError('Includes from anonymous input require include_base_dir')
        else:
            base = ''

        sources = []
        included = []
        for pattern in patterns:
            if not pattern:
                continue
            pattern = os.path.abspath(os.path.join(base, os.path.expanduser(pattern)))
            # Existing literal bracketed filenames need no glob interpretation.
            if os.path.isfile(pattern) or not glob.has_magic(pattern):
                paths = [pattern]
            else:
                paths = sorted(glob.glob(pattern))
            for path in paths:
                try:
                    child = ConfigObj(path, **options)
                except ConfigObjError as error:
                    raise ConfigObjError('Cannot include %s: %s' % (path, error)) from error
                included.append(path)
                included.extend(expand(child, chain))
                sources.append(child)

        # Read and expand every input before altering the current tree. Sections
        # are copied into their final parent, never borrowed from another root.
        local = ConfigObj(interpolation=False)
        merge(local, current, skip=key)
        spec = current.configspec
        current.clear()
        for source in sources:
            merge(current, source)
        merge(current, local)
        current.configspec = spec
        return included

    config.included_files = tuple(expand(config, []))
