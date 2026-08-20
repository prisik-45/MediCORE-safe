from types import SimpleNamespace
from uuid import UUID, uuid4

from backend.app.models import Profile
from backend.app.services.tenant_ai_settings import ai_settings_tenant_id


class FakeQuery:
    def __init__(self, profile):
        self.profile = profile

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.profile


class FakeDb:
    def __init__(self, profile=None):
        self.profile = profile

    def query(self, model):
        assert model is Profile
        return FakeQuery(self.profile)


def test_employee_ai_settings_use_admin_tenant_id():
    admin_tenant_id = uuid4()
    employee_id = uuid4()
    profile = SimpleNamespace(id=employee_id, role="employee", tenant_id=admin_tenant_id)

    assert ai_settings_tenant_id(FakeDb(profile), employee_id) == admin_tenant_id


def test_admin_ai_settings_use_current_tenant_id():
    admin_tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    profile = SimpleNamespace(id=admin_tenant_id, role="admin", tenant_id=admin_tenant_id)

    assert ai_settings_tenant_id(FakeDb(profile), admin_tenant_id) == admin_tenant_id
