"""Tests for KnowledgeBaseService DI hardening (Sprint A.12).

The constructor previously fell back to ``KbPermissionRepository.__new__`` —
an uninitialized instance with no session factory. Any access-control
or permission-management call would then explode with an obscure
``AttributeError`` instead of failing fast at construction time.

We now require ``permission_repo`` explicitly. A clear ValueError makes
the misconfiguration impossible to ship.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deerflow.knowledge_base.service import KnowledgeBaseService


class TestServiceRequiresPermissionRepo:
    def test_omitted_permission_repo_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="KbPermissionRepository"):
            KnowledgeBaseService(
                kb_repo=MagicMock(),
                doc_repo=MagicMock(),
                job_repo=MagicMock(),
            )

    def test_explicit_none_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="KbPermissionRepository"):
            KnowledgeBaseService(
                kb_repo=MagicMock(),
                doc_repo=MagicMock(),
                job_repo=MagicMock(),
                permission_repo=None,
            )

    def test_concrete_repo_constructs(self) -> None:
        perm_repo = MagicMock()
        svc = KnowledgeBaseService(
            kb_repo=MagicMock(),
            doc_repo=MagicMock(),
            job_repo=MagicMock(),
            permission_repo=perm_repo,
        )
        assert svc.permission_repo is perm_repo
