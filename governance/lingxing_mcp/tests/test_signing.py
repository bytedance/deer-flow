from governance_lingxing_mcp.signing import sign_request


def test_sign_request_known_value():
    """用端到端验证过的参数 + 期望签名做锚点。

    该锚点值由 sign_request 对固定 params 计算得出（确定性签名）。
    若 AES mode/padding/key 补齐逻辑回归，此断言会失败。
    """
    params = {
        "access_token": "46c765a0-6bf6-43df-bab8-16aeed7b40be",
        "app_key": "ak_Wwkrr5Y4eRBpb",
        "timestamp": "1753699052",  # 验证时的时间戳
    }
    sign = sign_request(params, app_id="ak_Wwkrr5Y4eRBpb")
    # 真实锚点：URL 编码的 Base64 字符串（确定性，回归会失配）
    assert sign == "%2BdqMEcWf6ADhxWBLhQaGzvctsBfvwuJvCm6LdH9j94T3eZCviNDUByaLNySQLIse"


def test_sign_request_deterministic():
    """相同参数产生相同签名。"""
    params = {"access_token": "tok", "app_key": "ak_test", "timestamp": "123"}
    s1 = sign_request(params, app_id="ak_test")
    s2 = sign_request(params, app_id="ak_test")
    assert s1 == s2


def test_sign_request_sorted_params():
    """参数顺序不影响签名（内部排序）。"""
    p1 = {"b": "2", "a": "1", "c": "3"}
    p2 = {"c": "3", "a": "1", "b": "2"}
    s1 = sign_request(p1, app_id="ak_test")
    s2 = sign_request(p2, app_id="ak_test")
    assert s1 == s2


def test_sign_request_removes_sign_field():
    """sign 字段不参与签名。"""
    params = {"a": "1", "sign": "old_value"}
    s1 = sign_request(params, app_id="ak_test")
    params2 = {"a": "1"}
    s2 = sign_request(params2, app_id="ak_test")
    assert s1 == s2
