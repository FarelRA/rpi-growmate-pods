import copy
import logging
import os
import pytest
import yaml
from pathlib import Path
from pydantic import ValidationError
from unittest.mock import MagicMock, mock_open, call, ANY, PropertyMock
from config_manager import ConfigManager, CONFIG_FILE, CONFIG_VERSION, load_config, save_config, is_provisioned


class TestConstructor:
    def test_default_path(self):
        mgr = ConfigManager()
        assert mgr.config_path == CONFIG_FILE
        assert mgr.enable_validation is True
        assert mgr.config == {}
        assert mgr.reload_callbacks == []

    def test_custom_path_and_no_validation(self):
        p = Path("/tmp/custom.yaml")
        mgr = ConfigManager(config_path=p, enable_validation=False)
        assert mgr.config_path == p
        assert mgr.enable_validation is False


class TestLoad:
    def test_missing_file_returns_defaults(self, mocker):
        mocker.patch.object(Path, 'exists', return_value=False)
        mgr = ConfigManager()
        cfg = mgr.load()
        assert cfg['version'] == 9
        assert 'device' in cfg
        assert 'network' in cfg

    def test_valid_yaml(self, mocker):
        data = {'version': 9, 'network': {'provisioned': True, 'wifi_ssid': 'mywifi'}}
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(data))
        mocker.patch('builtins.open', m)
        mocker.patch('config_manager.ConfigManager.validate', return_value=True)
        mgr = ConfigManager()
        result = mgr.load()
        assert result['network']['provisioned'] is True
        assert result['network']['wifi_ssid'] == 'mywifi'

    def test_invalid_yaml_raises_error(self, mocker):
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data="{invalid: yaml: [broken")
        mocker.patch('builtins.open', m)
        mgr = ConfigManager()
        with pytest.raises(yaml.YAMLError):
            mgr.load()

    def test_version_mismatch(self, mocker):
        data = {'version': 1, 'network': {'provisioned': False, 'wifi_ssid': ''}}
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(data))
        mocker.patch('builtins.open', m)
        mocker.patch('config_manager.ConfigManager.validate', return_value=True)
        mgr = ConfigManager()
        mgr.load()
        assert mgr.config['version'] == 1

    def test_validation_disabled_skips_validate(self, mocker):
        data = {'version': 9, 'network': {'provisioned': False, 'wifi_ssid': ''}}
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(data))
        mocker.patch('builtins.open', m)
        mock_validate = mocker.patch('config_manager.ConfigManager.validate')
        mgr = ConfigManager(enable_validation=False)
        mgr.load()
        mock_validate.assert_not_called()

    def test_empty_yaml_returns_empty_dict(self, mocker):
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data="")
        mocker.patch('builtins.open', m)
        mocker.patch('config_manager.ConfigManager.validate', return_value=True)
        mgr = ConfigManager()
        result = mgr.load()
        assert result == {}

    def test_env_overrides_applied_during_load(self, mocker, monkeypatch):
        data = {'version': 9, 'intervals': {'sensor_reading': 60}}
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(data))
        mocker.patch('builtins.open', m)
        mocker.patch('config_manager.ConfigManager.validate', return_value=True)
        monkeypatch.setenv('GROWMATE_INTERVALS_SENSOR_READING', '120')
        mgr = ConfigManager()
        result = mgr.load()
        assert result['intervals']['sensor_reading'] == 120


class TestSave:
    def test_writes_yaml_to_file(self, mocker):
        mock_parent = MagicMock()
        mocker.patch.object(Path, 'parent', new_callable=PropertyMock, return_value=mock_parent)
        m = mock_open()
        mocker.patch('builtins.open', m)
        mocker.patch('yaml.safe_dump')
        mgr = ConfigManager()
        mgr.config = {'version': 9, 'test': True}
        mgr.save()
        mock_parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        m.assert_called_once_with(mgr.config_path, 'w')

    def test_creates_parent_directories(self, mocker):
        mock_parent = MagicMock()
        mocker.patch.object(Path, 'parent', new_callable=PropertyMock, return_value=mock_parent)
        m = mock_open()
        mocker.patch('builtins.open', m)
        mocker.patch('yaml.safe_dump')
        mgr = ConfigManager(config_path=Path("/a/b/c.yaml"))
        mgr.config = {'version': 9}
        mgr.save()
        mock_parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_ioerror_on_write(self, mocker):
        mock_parent = MagicMock()
        mocker.patch.object(Path, 'parent', new_callable=PropertyMock, return_value=mock_parent)
        m = mock_open()
        m.side_effect = IOError("Disk full")
        mocker.patch('builtins.open', m)
        mgr = ConfigManager()
        mgr.config = {'version': 9}
        with pytest.raises(IOError, match="Disk full"):
            mgr.save()

    def test_save_with_explicit_config(self, mocker):
        mock_parent = MagicMock()
        mocker.patch.object(Path, 'parent', new_callable=PropertyMock, return_value=mock_parent)
        m = mock_open()
        mocker.patch('builtins.open', m)
        mocker.patch('yaml.safe_dump')
        mgr = ConfigManager()
        mgr.config = {'old': True}
        mgr.save({'new': True})
        assert mgr.config == {'new': True}


class TestIsProvisioned:
    def test_provisioned_with_wifi_ssid(self):
        mgr = ConfigManager()
        mgr.config = {'network': {'provisioned': True, 'wifi_ssid': 'MyWiFi'}}
        assert mgr.is_provisioned() is True

    def test_not_provisioned(self):
        mgr = ConfigManager()
        mgr.config = {'network': {'provisioned': False, 'wifi_ssid': ''}}
        assert mgr.is_provisioned() is False

    def test_no_wifi_ssid(self):
        mgr = ConfigManager()
        mgr.config = {'network': {'provisioned': True, 'wifi_ssid': ''}}
        assert mgr.is_provisioned() is False

    def test_empty_config(self):
        mgr = ConfigManager()
        mgr.config = {}
        assert mgr.is_provisioned() is False

    def test_provisioned_whitespace_ssid(self):
        mgr = ConfigManager()
        mgr.config = {'network': {'provisioned': True, 'wifi_ssid': '   '}}
        assert mgr.is_provisioned() is False


class TestGet:
    def test_dot_notation(self):
        mgr = ConfigManager()
        mgr.config = {'network': {'wifi': {'interface': 'wlan0'}}}
        assert mgr.get('network.wifi.interface') == 'wlan0'

    def test_missing_key_with_default(self):
        mgr = ConfigManager()
        mgr.config = {'network': {}}
        assert mgr.get('network.nonexistent', 'fallback') == 'fallback'

    def test_missing_key_returns_none(self):
        mgr = ConfigManager()
        mgr.config = {}
        assert mgr.get('nonexistent') is None

    def test_non_dict_intermediate_returns_default(self):
        mgr = ConfigManager()
        mgr.config = {'network': 'not_a_dict'}
        assert mgr.get('network.wifi_ssid', 42) == 42


class TestSet:
    def test_dot_notation(self):
        mgr = ConfigManager()
        mgr.config = {}
        mgr.set('network.wifi_ssid', 'test')
        assert mgr.config['network']['wifi_ssid'] == 'test'

    def test_creates_intermediate_dicts(self):
        mgr = ConfigManager()
        mgr.config = {}
        mgr.set('a.b.c.d', 'deep')
        assert mgr.config['a']['b']['c']['d'] == 'deep'

    def test_overwrites_existing(self):
        mgr = ConfigManager()
        mgr.config = {'network': {'wifi_ssid': 'old'}}
        mgr.set('network.wifi_ssid', 'new')
        assert mgr.config['network']['wifi_ssid'] == 'new'


class TestEnvOverrides:
    def test_get_env_override_device_id(self, monkeypatch):
        monkeypatch.setenv('DEVICE_ID', 'my-device')
        val = ConfigManager._get_env_override('device.id')
        assert val == 'growmate-my-device'

    def test_get_env_override_api_key(self, monkeypatch):
        monkeypatch.setenv('DEVICE_API_KEY', 'sk-123')
        val = ConfigManager._get_env_override('api.api_key')
        assert val == 'sk-123'

    def test_get_env_override_growmate_pattern(self, monkeypatch):
        monkeypatch.setenv('GROWMATE_INTERVALS_SENSOR_READING', '99')
        val = ConfigManager._get_env_override('intervals.sensor_reading')
        assert val == '99'

    def test_get_env_override_no_match(self):
        val = ConfigManager._get_env_override('intervals.sensor_reading')
        assert val is None

    def test_apply_bool_override(self, monkeypatch):
        monkeypatch.setenv('GROWMATE_FEATURES_OFFLINE_QUEUE', 'false')
        cfg = {'features': {'offline_queue': True}}
        mgr = ConfigManager()
        mgr._apply_env_overrides(cfg)
        assert cfg['features']['offline_queue'] is False

    def test_apply_int_override(self, monkeypatch):
        monkeypatch.setenv('GROWMATE_INTERVALS_SENSOR_READING', '150')
        cfg = {'intervals': {'sensor_reading': 60}}
        mgr = ConfigManager()
        mgr._apply_env_overrides(cfg)
        assert cfg['intervals']['sensor_reading'] == 150

    def test_apply_float_override(self, monkeypatch):
        monkeypatch.setenv('GROWMATE_RETRY_INITIAL_DELAY', '2.5')
        cfg = {'retry': {'initial_delay': 1.0}}
        mgr = ConfigManager()
        mgr._apply_env_overrides(cfg)
        assert cfg['retry']['initial_delay'] == 2.5

    def test_apply_string_override(self, monkeypatch):
        monkeypatch.setenv('GROWMATE_NETWORK_WIFI_SSID', 'MyNetwork')
        cfg = {'network': {'wifi_ssid': 'old'}}
        mgr = ConfigManager()
        mgr._apply_env_overrides(cfg)
        assert cfg['network']['wifi_ssid'] == 'MyNetwork'

    def test_apply_env_override_invalid_int_skips(self, monkeypatch, mocker):
        monkeypatch.setenv('GROWMATE_INTERVALS_SENSOR_READING', 'not_an_int')
        cfg = {'intervals': {'sensor_reading': 60}}
        mgr = ConfigManager()
        mocker.patch('config_manager.logger')
        mgr._apply_env_overrides(cfg)
        assert cfg['intervals']['sensor_reading'] == 60

    def test_apply_env_override_invalid_float_skips(self, monkeypatch, mocker):
        monkeypatch.setenv('GROWMATE_RETRY_INITIAL_DELAY', 'not_a_float')
        cfg = {'retry': {'initial_delay': 1.0}}
        mgr = ConfigManager()
        mocker.patch('config_manager.logger')
        mgr._apply_env_overrides(cfg)
        assert cfg['retry']['initial_delay'] == 1.0

    def test_device_id_mapped_correctly(self, monkeypatch):
        monkeypatch.setenv('DEVICE_ID', 'env-device')
        cfg = {'device': {'id': 'default'}}
        mgr = ConfigManager()
        mgr._apply_env_overrides(cfg)
        assert cfg['device']['id'] == 'growmate-env-device'

    def test_bool_override_true_values(self, monkeypatch):
        monkeypatch.setenv('GROWMATE_FEATURES_OFFLINE_QUEUE', '1')
        cfg = {'features': {'offline_queue': False}}
        mgr = ConfigManager()
        mgr._apply_env_overrides(cfg)
        assert cfg['features']['offline_queue'] is True


class TestUpdateFromOnboarding:
    def test_sets_provisioned_version_and_wifi(self):
        mgr = ConfigManager()
        mgr.config = {}
        mgr.update_from_onboarding('MyWiFi', 'secret123')
        assert mgr.config['version'] == 9
        assert mgr.config['network']['provisioned'] is True
        assert mgr.config['network']['wifi_ssid'] == 'MyWiFi'
        assert mgr.config['network']['wifi_password'] == 'secret123'

    def test_strips_ssid_whitespace(self):
        mgr = ConfigManager()
        mgr.config = {}
        mgr.update_from_onboarding('  MyWiFi  ', 'secret123')
        assert mgr.config['network']['wifi_ssid'] == 'MyWiFi'


class TestValidate:
    def test_validate_passes(self, mocker):
        mock_validate = mocker.patch('config_validator.validate_config')
        mgr = ConfigManager()
        result = mgr.validate({'version': 9})
        assert result is True
        mock_validate.assert_called_once_with({'version': 9})

    def test_validate_raises_validation_error(self, mocker):
        mock_validate = mocker.patch(
            'config_validator.validate_config',
            side_effect=ValidationError.from_exception_data("test", [])
        )
        mgr = ConfigManager()
        with pytest.raises(ValidationError):
            mgr.validate({'version': -1})

    def test_validate_defaults_to_current_config(self, mocker):
        mock_validate = mocker.patch('config_validator.validate_config')
        mgr = ConfigManager()
        mgr.config = {'version': 9}
        mgr.validate()
        mock_validate.assert_called_once_with({'version': 9})


class TestReload:
    def test_reload_success_with_changes(self, mocker):
        initial = {
            'version': 9,
            'device': {'id': 'test'},
            'network': {'provisioned': False, 'wifi_ssid': '', 'wifi_password': ''},
            'intervals': {'sensor_reading': 60, 'failure_monitor': 30},
        }
        new_data = {
            'version': 9,
            'device': {'id': 'test'},
            'network': {'provisioned': False, 'wifi_ssid': '', 'wifi_password': ''},
            'intervals': {'sensor_reading': 120, 'failure_monitor': 30},
        }
        mgr = ConfigManager()
        mgr.config = copy.deepcopy(initial)
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(new_data))
        mocker.patch('builtins.open', m)
        mocker.patch('config_manager.ConfigManager.validate', return_value=True)
        changes = mgr.reload()
        assert 'intervals.sensor_reading' in changes
        assert changes['intervals.sensor_reading'] == (60, 120)
        assert mgr.config['intervals']['sensor_reading'] == 120

    def test_reload_file_not_found(self):
        mgr = ConfigManager(config_path=Path("/nonexistent/config.yaml"))
        mgr.config = {'version': 9}
        with pytest.raises(FileNotFoundError):
            mgr.reload()

    def test_reload_invalid_yaml(self, mocker):
        mgr = ConfigManager()
        mgr.config = {'version': 9}
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data="[invalid:: yaml")
        mocker.patch('builtins.open', m)
        with pytest.raises(yaml.YAMLError):
            mgr.reload()

    def test_reload_validation_error_keeps_old_config(self, mocker):
        initial = {'version': 9, 'intervals': {'sensor_reading': 60}}
        new_data = {'version': 9, 'intervals': {'sensor_reading': 999}}
        mgr = ConfigManager()
        mgr.config = copy.deepcopy(initial)
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(new_data))
        mocker.patch('builtins.open', m)
        mocker.patch(
            'config_manager.ConfigManager.validate',
            side_effect=ValidationError.from_exception_data("test", [])
        )
        with pytest.raises(ValidationError):
            mgr.reload()
        assert mgr.config['intervals']['sensor_reading'] == 60

    def test_reload_non_reloadable_change_raises_value_error(self, mocker):
        initial = {
            'version': 9,
            'device': {'id': 'test'},
            'network': {'provisioned': False, 'wifi_ssid': '', 'wifi_password': ''},
        }
        new_data = {
            'version': 9,
            'device': {'id': 'test'},
            'network': {'provisioned': True, 'wifi_ssid': 'new', 'wifi_password': ''},
        }
        mgr = ConfigManager()
        mgr.config = copy.deepcopy(initial)
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(new_data))
        mocker.patch('builtins.open', m)
        mocker.patch('config_manager.ConfigManager.validate', return_value=True)
        with pytest.raises(ValueError, match="Non-reloadable"):
            mgr.reload()
        assert mgr.config['network']['provisioned'] is False

    def test_reload_no_changes_returns_empty_dict(self, mocker):
        data = {'version': 9, 'intervals': {'sensor_reading': 60}}
        mgr = ConfigManager()
        mgr.config = copy.deepcopy(data)
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(data))
        mocker.patch('builtins.open', m)
        mocker.patch('config_manager.ConfigManager.validate', return_value=True)
        changes = mgr.reload()
        assert changes == {}

    def test_reload_env_overrides_applied_to_new_config(self, mocker, monkeypatch):
        initial = {'version': 9, 'intervals': {'sensor_reading': 60, 'failure_monitor': 30}}
        new_data = {'version': 9, 'intervals': {'sensor_reading': 120, 'failure_monitor': 30}}
        mgr = ConfigManager()
        mgr.config = copy.deepcopy(initial)
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(new_data))
        mocker.patch('builtins.open', m)
        mocker.patch('config_manager.ConfigManager.validate', return_value=True)
        monkeypatch.setenv('GROWMATE_INTERVALS_SENSOR_READING', '180')
        changes = mgr.reload()
        assert mgr.config['intervals']['sensor_reading'] == 180
        assert changes['intervals.sensor_reading'] == (60, 180)

    def test_reload_notifies_callbacks(self, mocker):
        initial = {
            'version': 9,
            'device': {'id': 'test'},
            'network': {'provisioned': False, 'wifi_ssid': '', 'wifi_password': ''},
            'intervals': {'sensor_reading': 60, 'failure_monitor': 30},
        }
        new_data = {
            'version': 9,
            'device': {'id': 'test'},
            'network': {'provisioned': False, 'wifi_ssid': '', 'wifi_password': ''},
            'intervals': {'sensor_reading': 120, 'failure_monitor': 30},
        }
        mgr = ConfigManager()
        mgr.config = copy.deepcopy(initial)
        mocker.patch.object(Path, 'exists', return_value=True)
        m = mock_open(read_data=yaml.dump(new_data))
        mocker.patch('builtins.open', m)
        mocker.patch('config_manager.ConfigManager.validate', return_value=True)
        mock_notify = mocker.patch('config_manager.ConfigManager._notify_reload_callbacks')
        mgr.reload()
        mock_notify.assert_called_once()
        args = mock_notify.call_args[0][0]
        assert 'intervals.sensor_reading' in args


class TestCallbacks:
    def test_register_callback(self):
        mgr = ConfigManager()
        cb = lambda x: None
        mgr.register_reload_callback(cb)
        assert cb in mgr.reload_callbacks

    def test_register_duplicate_is_idempotent(self):
        mgr = ConfigManager()
        cb = lambda x: None
        mgr.register_reload_callback(cb)
        mgr.register_reload_callback(cb)
        assert len(mgr.reload_callbacks) == 1

    def test_unregister_callback(self):
        mgr = ConfigManager()
        cb = lambda x: None
        mgr.register_reload_callback(cb)
        mgr.unregister_reload_callback(cb)
        assert cb not in mgr.reload_callbacks

    def test_unregister_non_registered(self):
        mgr = ConfigManager()
        cb = lambda x: None
        mgr.unregister_reload_callback(cb)
        assert mgr.reload_callbacks == []

    def test_notify_callbacks_called_with_changes(self, mocker):
        mocker.patch('config_manager.logger')
        mgr = ConfigManager()
        received = []
        def cb(changes):
            received.append(changes)
        mgr.register_reload_callback(cb)
        mgr._notify_reload_callbacks({'key': ('old', 'new')})
        assert received == [{'key': ('old', 'new')}]

    def test_notify_callbacks_handles_exception(self, mocker):
        mocker.patch('config_manager.logger')
        mgr = ConfigManager()
        def cb1(changes):
            raise Exception("oops")
        received = []
        def cb2(changes):
            received.append(changes)
        mgr.register_reload_callback(cb1)
        mgr.register_reload_callback(cb2)
        mgr._notify_reload_callbacks({'k': ('o', 'n')})
        assert received == [{'k': ('o', 'n')}]


class TestResetToDefaults:
    def test_resets_and_saves(self, mocker):
        mgr = ConfigManager()
        mgr.config = {'version': 1, 'device': {'id': 'old'}}
        mock_save = mocker.patch.object(mgr, 'save')
        mgr.reset_to_defaults()
        assert mgr.config['version'] == 9
        assert 'device' in mgr.config
        assert 'network' in mgr.config
        mock_save.assert_called_once()


class TestGetDefaultConfig:
    def test_returns_full_schema(self):
        cfg = ConfigManager.get_default_config()
        assert cfg['version'] == CONFIG_VERSION


class TestStandaloneFunctions:
    def test_load_config(self, mocker):
        mock_load = mocker.patch('config_manager.ConfigManager.load', return_value={'version': 9})
        result = load_config(Path("/custom.yaml"))
        assert result == {'version': 9}
        mock_load.assert_called_once()

    def test_save_config(self, mocker):
        mock_save = mocker.patch('config_manager.ConfigManager.save')
        cfg = {'version': 9}
        save_config(cfg, Path("/custom.yaml"))
        mock_save.assert_called_once_with(cfg)

    def test_is_provisioned(self, mocker):
        mock_load = mocker.patch('config_manager.ConfigManager.load')
        mock_prov = mocker.patch('config_manager.ConfigManager.is_provisioned', return_value=True)
        result = is_provisioned(Path("/custom.yaml"))
        assert result is True
        mock_load.assert_called_once()
        mock_prov.assert_called_once()
