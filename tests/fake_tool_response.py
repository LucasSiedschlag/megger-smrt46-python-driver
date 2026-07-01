from __future__ import annotations

from typing import Any, Dict, List, Optional


class FakeToolResponse:
    def __init__(
        self,
        *,
        success: bool = True,
        final_state: str = "COMPLETE",
        result: Optional[Dict[str, Any]] = None,
        warnings: Optional[List[str]] = None,
        test_name: Optional[str] = None,
    ) -> None:
        self.success = success
        self.final_state = final_state
        self.result = result or {}
        self.warnings = warnings or []
        self.test_name = test_name

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "equip": "smrt46",
            "success": self.success,
            "final_state": self.final_state,
            "result": self.result,
            "warnings": self.warnings,
        }
        if self.test_name is not None:
            payload["test_name"] = self.test_name
        return payload
