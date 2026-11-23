import pytest

from configobj import ConfigObj
from configobj.validate import Validator, VdtMissingValue, VdtTypeError


@pytest.mark.parametrize('check', [
    'float(min=0, max=1, default=0.5)',
    'integer(min=0, max=10, default=5)',
    'float(min=0, max=1)',
    'boolean',
    'string(min=1)',
    'list(min=1)',
    "string(default='None')",
])
def test_supplied_none_is_checked_against_its_type(check):
    with pytest.raises(VdtTypeError):
        Validator().check(check, None)


def test_none_default_remains_optional_and_can_be_validated_again():
    validator = Validator()
    check = 'float(min=0, max=1, default=None)'
    assert validator.check(check, None, missing=True) is None
    assert validator.check(check, None) is None
    assert validator.check(check, '0.5') == 0.5
    config = ConfigObj({}, configspec=['value = ' + check])
    assert config.validate(validator) is True
    assert config['value'] is None
    assert config.validate(validator) is True


def test_missing_values_still_use_defaults():
    validator = Validator()
    assert validator.check('float(default=0.5)', None, missing=True) == 0.5
    assert validator.check("string(default='None')", None, missing=True) == 'None'
    with pytest.raises(VdtMissingValue):
        validator.check('float', None, missing=True)


def test_none_reaches_custom_validators():
    seen = []

    def custom(value):
        seen.append(value)
        raise VdtTypeError(value)

    validator = Validator({'custom': custom})
    with pytest.raises(VdtTypeError):
        validator.check('custom', None)
    assert seen == [None]


def test_configobj_rejects_explicit_none_for_a_bounded_value():
    config = ConfigObj({'value': None},
                       configspec=['value = float(min=0, max=1, default=0.5)'])
    result = config.validate(Validator(), preserve_errors=True)
    assert isinstance(result, dict)
    assert isinstance(result['value'], VdtTypeError)
