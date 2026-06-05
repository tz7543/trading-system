import pytest

from core.data_handler import DataHandler


def test_data_handler_cannot_be_instantiated():
    with pytest.raises(TypeError):
        DataHandler()
