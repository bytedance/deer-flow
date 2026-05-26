"""
性能测试：技能列表 API 增加 tier 字段后响应时间不退化

Task 9.3: 验证技能 API 在增加 tier 字段后的性能表现
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.gateway.app import app


@pytest.fixture(scope="module")
def client():
    """创建测试客户端"""
    return TestClient(app)


class TestSkillsAPIPerformance:
    """技能 API 性能测试"""

    def test_list_skills_response_time(self, client):
        """
        测试 GET /api/skills 响应时间
        要求：平均响应时间 < 100ms（包含 tier 字段）
        """
        # 预热
        client.get("/api/skills")

        # 测量 10 次请求的平均响应时间
        response_times = []
        for _ in range(10):
            start = time.perf_counter()
            response = client.get("/api/skills")
            end = time.perf_counter()

            assert response.status_code == 200
            response_times.append((end - start) * 1000)  # 转换为毫秒

        avg_response_time = sum(response_times) / len(response_times)
        max_response_time = max(response_times)

        print(f"\n平均响应时间: {avg_response_time:.2f}ms")
        print(f"最大响应时间: {max_response_time:.2f}ms")

        # 平均响应时间应小于 100ms
        assert avg_response_time < 100, (
            f"平均响应时间 {avg_response_time:.2f}ms 超过阈值 100ms"
        )

    def test_list_skills_with_tier_filter_performance(self, client):
        """
        测试 GET /api/skills?tier=core-industrial 响应时间
        要求：过滤请求不应显著增加响应时间
        """
        # 预热
        client.get("/api/skills?tier=core-industrial")
        client.get("/api/skills?tier=foundation")

        # 测量无过滤的响应时间
        baseline_times = []
        for _ in range(5):
            start = time.perf_counter()
            response = client.get("/api/skills")
            end = time.perf_counter()
            assert response.status_code == 200
            baseline_times.append((end - start) * 1000)

        # 测量有过滤的响应时间
        filtered_times = []
        for _ in range(5):
            start = time.perf_counter()
            response = client.get("/api/skills?tier=core-industrial")
            end = time.perf_counter()
            assert response.status_code == 200
            filtered_times.append((end - start) * 1000)

        avg_baseline = sum(baseline_times) / len(baseline_times)
        avg_filtered = sum(filtered_times) / len(filtered_times)

        print(f"\n无过滤平均响应时间: {avg_baseline:.2f}ms")
        print(f"有过滤平均响应时间: {avg_filtered:.2f}ms")

        # 过滤不应增加超过 20ms 的响应时间
        assert avg_filtered < avg_baseline + 20, (
            f"过滤请求增加了过多响应时间: {avg_filtered - avg_baseline:.2f}ms"
        )

    def test_skill_response_includes_tier_field(self, client):
        """
        验证技能响应包含 tier 字段
        """
        response = client.get("/api/skills")
        assert response.status_code == 200

        data = response.json()
        skills = data.get("skills", [])

        if len(skills) > 0:
            # 验证每个技能都包含 tier 字段
            for skill in skills:
                assert "tier" in skill, f"技能 {skill.get('name')} 缺少 tier 字段"
                assert skill["tier"] in ["core-industrial", "foundation"], (
                    f"技能 {skill.get('name')} 的 tier 值无效: {skill['tier']}"
                )

    def test_skill_tier_filter_returns_correct_skills(self, client):
        """
        验证 tier 过滤返回正确的技能
        """
        # 获取所有技能
        all_response = client.get("/api/skills")
        assert all_response.status_code == 200
        all_skills = all_response.json().get("skills", [])

        # 获取 core-industrial 技能
        industrial_response = client.get("/api/skills?tier=core-industrial")
        assert industrial_response.status_code == 200
        industrial_skills = industrial_response.json().get("skills", [])

        # 获取 foundation 技能
        foundation_response = client.get("/api/skills?tier=foundation")
        assert foundation_response.status_code == 200
        foundation_skills = foundation_response.json().get("skills", [])

        # 验证过滤结果
        assert len(industrial_skills) + len(foundation_skills) == len(all_skills), (
            "过滤后的技能数量之和不等于全部技能数量"
        )

        # 验证 core-industrial 技能都正确
        for skill in industrial_skills:
            assert skill["tier"] == "core-industrial"

        # 验证 foundation 技能都正确
        for skill in foundation_skills:
            assert skill["tier"] == "foundation"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
