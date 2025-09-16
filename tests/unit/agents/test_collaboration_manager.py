"""
协作管理器单元测试
测试Agent协作、任务分配和协作模式功能
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.agents.collaboration_manager import (
    CollaborationManager, AgentRole, CollaborationPattern,
    CollaborationRequest, CollaborationResponse, get_collaboration_manager
)
from src.prompts.planner_model import Step, StepType


class TestCollaborationManager:
    """CollaborationManager类的单元测试"""
    
    def setup_method(self):
        """测试前的设置"""
        self.manager = CollaborationManager()
    
    def test_init(self):
        """测试CollaborationManager初始化"""
        assert self.manager is not None
        assert hasattr(self.manager, 'find_suitable_agent')
        assert hasattr(self.manager, 'create_collaboration_request')
        assert hasattr(self.manager, 'process_collaboration_request')
    
    def test_find_suitable_agent_research(self):
        """测试寻找研究类Agent"""
        capabilities = ["信息搜索", "数据收集", "文献调研"]
        
        agent = self.manager.find_suitable_agent(capabilities)
        
        assert agent is not None
        assert isinstance(agent, AgentRole)
        # 研究相关能力应该匹配到RESEARCHER
        assert agent in [AgentRole.RESEARCHER, AgentRole.ANALYST]
    
    def test_find_suitable_agent_coding(self):
        """测试寻找编程类Agent"""
        capabilities = ["代码分析", "算法实现", "数据处理"]
        
        agent = self.manager.find_suitable_agent(capabilities)
        
        assert agent is not None
        assert isinstance(agent, AgentRole)
        # 编程相关能力应该匹配到CODER
        assert agent in [AgentRole.CODER, AgentRole.ANALYST]
    
    def test_find_suitable_agent_with_exclusion(self):
        """测试排除特定Agent的搜索"""
        capabilities = ["信息搜索", "数据收集"]
        exclude_agents = {AgentRole.RESEARCHER}
        
        agent = self.manager.find_suitable_agent(capabilities, exclude_agents)
        
        if agent is not None:
            assert agent not in exclude_agents
    
    def test_create_collaboration_request(self):
        """测试创建协作请求"""
        request = self.manager.create_collaboration_request(
            requesting_agent=AgentRole.PLANNER,
            target_agent=AgentRole.RESEARCHER,
            task_description="收集市场数据",
            required_capabilities=["数据收集", "市场分析"],
            priority=1
        )
        
        assert isinstance(request, CollaborationRequest)
        assert request.requesting_agent == AgentRole.PLANNER
        assert request.target_agent == AgentRole.RESEARCHER
        assert request.task_description == "收集市场数据"
        assert "数据收集" in request.required_capabilities
        assert request.priority == 1
    
    def test_process_collaboration_request_sequential(self):
        """测试处理顺序协作请求"""
        request = CollaborationRequest(
            request_id="test_request",
            requesting_agent=AgentRole.PLANNER,
            target_agent=AgentRole.RESEARCHER,
            task_description="数据收集任务",
            required_capabilities=["数据收集"],
            collaboration_pattern=CollaborationPattern.SEQUENTIAL,
            priority=1
        )
        
        execution_result = {"data": "收集的数据", "status": "完成"}
        
        response = self.manager.process_collaboration_request(
            request.request_id, execution_result
        )
        
        assert isinstance(response, CollaborationResponse)
        assert response.request_id == request.request_id
        assert response.success is True
        assert response.result == execution_result
    
    def test_process_collaboration_request_parallel(self):
        """测试处理并行协作请求"""
        request = CollaborationRequest(
            request_id="parallel_request",
            requesting_agent=AgentRole.COORDINATOR,
            target_agent=AgentRole.ANALYST,
            task_description="并行数据分析",
            required_capabilities=["数据分析"],
            collaboration_pattern=CollaborationPattern.PARALLEL,
            priority=2
        )
        
        # 注册请求
        self.manager.active_requests[request.request_id] = request
        
        execution_result = {"analysis": "分析结果", "confidence": 0.85}
        
        response = self.manager.process_collaboration_request(
            request.request_id, execution_result
        )
        
        assert isinstance(response, CollaborationResponse)
        assert response.success is True
        assert "parallel" in response.metadata.get("collaboration_pattern", "")
    
    def test_get_collaboration_info(self):
        """测试获取协作信息"""
        steps = [
            Step(
                step_id="step1",
                description="数据收集步骤",
                step_type=StepType.RESEARCH,
                expected_output="原始数据"
            ),
            Step(
                step_id="step2",
                description="数据分析步骤",
                step_type=StepType.PROCESSING,
                expected_output="分析结果"
            )
        ]
        
        collaboration_info = self.manager.get_collaboration_info(steps)
        
        assert isinstance(collaboration_info, dict)
        assert "agent_assignments" in collaboration_info
        assert "collaboration_patterns" in collaboration_info
        assert len(collaboration_info["agent_assignments"]) == len(steps)
    
    def test_determine_collaboration_pattern(self):
        """测试协作模式确定"""
        # 简单任务应该使用顺序协作
        simple_task = "收集基础信息"
        simple_capabilities = ["信息搜索"]
        
        pattern = self.manager._determine_collaboration_pattern(
            simple_task, simple_capabilities
        )
        assert pattern == CollaborationPattern.SEQUENTIAL
        
        # 复杂任务可能使用并行或层级协作
        complex_task = "多维度数据分析和可视化"
        complex_capabilities = ["数据分析", "可视化", "统计建模"]
        
        pattern = self.manager._determine_collaboration_pattern(
            complex_task, complex_capabilities
        )
        assert pattern in [CollaborationPattern.PARALLEL, CollaborationPattern.HIERARCHICAL]
    
    def test_agent_capability_matching(self):
        """测试Agent能力匹配"""
        # 测试研究员能力
        researcher_score = self.manager._calculate_capability_match(
            AgentRole.RESEARCHER, ["信息搜索", "文献调研", "数据收集"]
        )
        assert researcher_score > 0.5
        
        # 测试编程员能力
        coder_score = self.manager._calculate_capability_match(
            AgentRole.CODER, ["代码分析", "算法实现", "系统设计"]
        )
        assert coder_score > 0.5
        
        # 测试不匹配的能力
        mismatch_score = self.manager._calculate_capability_match(
            AgentRole.RESEARCHER, ["代码编写", "系统部署"]
        )
        assert mismatch_score < 0.5
    
    def test_communication_history(self):
        """测试通信历史记录"""
        request = CollaborationRequest(
            request_id="comm_test",
            requesting_agent=AgentRole.PLANNER,
            target_agent=AgentRole.RESEARCHER,
            task_description="测试通信",
            required_capabilities=["测试"],
            collaboration_pattern=CollaborationPattern.SEQUENTIAL,
            priority=1
        )
        
        # 记录通信
        self.manager._record_communication(request, {"result": "测试结果"})
        
        # 验证通信历史
        history = self.manager.get_communication_history(
            AgentRole.PLANNER, AgentRole.RESEARCHER
        )
        
        assert len(history) > 0
        assert any(comm["request_id"] == "comm_test" for comm in history)
    
    def test_shared_knowledge_base(self):
        """测试共享知识库"""
        # 添加知识
        knowledge_item = {
            "topic": "市场分析方法",
            "content": "详细的市场分析步骤和工具",
            "source_agent": AgentRole.ANALYST,
            "relevance_score": 0.9
        }
        
        self.manager.add_to_knowledge_base("market_analysis", knowledge_item)
        
        # 检索知识
        retrieved = self.manager.get_from_knowledge_base("market_analysis")
        
        assert retrieved is not None
        assert retrieved["topic"] == "市场分析方法"
        assert retrieved["source_agent"] == AgentRole.ANALYST
    
    def test_workload_balancing(self):
        """测试工作负载均衡"""
        # 模拟多个请求
        requests = []
        for i in range(5):
            request = CollaborationRequest(
                request_id=f"request_{i}",
                requesting_agent=AgentRole.COORDINATOR,
                target_agent=AgentRole.RESEARCHER,
                task_description=f"任务{i}",
                required_capabilities=["数据收集"],
                collaboration_pattern=CollaborationPattern.SEQUENTIAL,
                priority=1
            )
            requests.append(request)
            self.manager.active_requests[request.request_id] = request
        
        # 检查工作负载
        workload = self.manager.get_agent_workload(AgentRole.RESEARCHER)
        assert workload >= 5
        
        # 测试负载均衡建议
        alternative_agent = self.manager.suggest_alternative_agent(
            AgentRole.RESEARCHER, ["数据收集"]
        )
        assert alternative_agent != AgentRole.RESEARCHER or alternative_agent is None


class TestCollaborationRequest:
    """CollaborationRequest数据模型测试"""
    
    def test_collaboration_request_creation(self):
        """测试CollaborationRequest对象创建"""
        request = CollaborationRequest(
            request_id="test_request",
            requesting_agent=AgentRole.PLANNER,
            target_agent=AgentRole.RESEARCHER,
            task_description="测试任务",
            required_capabilities=["测试能力"],
            collaboration_pattern=CollaborationPattern.SEQUENTIAL,
            priority=1
        )
        
        assert request.request_id == "test_request"
        assert request.requesting_agent == AgentRole.PLANNER
        assert request.target_agent == AgentRole.RESEARCHER
        assert request.task_description == "测试任务"
        assert "测试能力" in request.required_capabilities
        assert request.collaboration_pattern == CollaborationPattern.SEQUENTIAL
        assert request.priority == 1
    
    def test_request_validation(self):
        """测试请求数据验证"""
        # 测试优先级范围
        with pytest.raises(ValueError):
            CollaborationRequest(
                request_id="invalid_priority",
                requesting_agent=AgentRole.PLANNER,
                target_agent=AgentRole.RESEARCHER,
                task_description="测试",
                required_capabilities=["测试"],
                collaboration_pattern=CollaborationPattern.SEQUENTIAL,
                priority=6  # 超出有效范围
            )


class TestCollaborationResponse:
    """CollaborationResponse数据模型测试"""
    
    def test_collaboration_response_creation(self):
        """测试CollaborationResponse对象创建"""
        response = CollaborationResponse(
            response_id="test_response",
            request_id="test_request",
            responding_agent=AgentRole.RESEARCHER,
            result={"data": "测试数据"},
            success=True,
            metadata={"execution_time": 1.5}
        )
        
        assert response.response_id == "test_response"
        assert response.request_id == "test_request"
        assert response.responding_agent == AgentRole.RESEARCHER
        assert response.result["data"] == "测试数据"
        assert response.success is True
        assert response.metadata["execution_time"] == 1.5


class TestAgentRole:
    """AgentRole枚举测试"""
    
    def test_agent_roles_exist(self):
        """测试所有Agent角色存在"""
        expected_roles = [
            "PLANNER", "RESEARCHER", "CODER", "ANALYST", 
            "COORDINATOR", "VALIDATOR", "REPORTER", "OPTIMIZER"
        ]
        
        for role_name in expected_roles:
            assert hasattr(AgentRole, role_name)
            role = getattr(AgentRole, role_name)
            assert isinstance(role, AgentRole)


class TestCollaborationPattern:
    """CollaborationPattern枚举测试"""
    
    def test_collaboration_patterns_exist(self):
        """测试所有协作模式存在"""
        expected_patterns = [
            "SEQUENTIAL", "PARALLEL", "HIERARCHICAL", "PEER_TO_PEER"
        ]
        
        for pattern_name in expected_patterns:
            assert hasattr(CollaborationPattern, pattern_name)
            pattern = getattr(CollaborationPattern, pattern_name)
            assert isinstance(pattern, CollaborationPattern)


class TestCollaborationManagerIntegration:
    """协作管理器集成测试"""
    
    def setup_method(self):
        """测试前的设置"""
        self.manager = CollaborationManager()
    
    def test_end_to_end_collaboration(self):
        """测试端到端协作流程"""
        # 1. 寻找合适的Agent
        capabilities = ["数据分析", "统计建模"]
        target_agent = self.manager.find_suitable_agent(capabilities)
        assert target_agent is not None
        
        # 2. 创建协作请求
        request = self.manager.create_collaboration_request(
            requesting_agent=AgentRole.COORDINATOR,
            target_agent=target_agent,
            task_description="执行数据分析任务",
            required_capabilities=capabilities,
            priority=2
        )
        assert isinstance(request, CollaborationRequest)
        
        # 3. 处理协作请求
        execution_result = {
            "analysis_results": "详细分析结果",
            "confidence": 0.92,
            "recommendations": ["建议1", "建议2"]
        }
        
        response = self.manager.process_collaboration_request(
            request.request_id, execution_result
        )
        
        assert isinstance(response, CollaborationResponse)
        assert response.success is True
        assert response.result == execution_result
    
    @patch('src.agents.collaboration_manager.get_step_coordinator')
    def test_step_coordinator_integration(self, mock_get_coordinator):
        """测试与步骤协调器的集成"""
        mock_coordinator = Mock()
        mock_get_coordinator.return_value = mock_coordinator
        
        steps = [
            Step(
                step_id="integration_test",
                description="集成测试步骤",
                step_type=StepType.RESEARCH,
                expected_output="测试结果"
            )
        ]
        
        collaboration_info = self.manager.get_collaboration_info(steps)
        
        assert isinstance(collaboration_info, dict)
        # 验证与步骤协调器的交互
        mock_get_coordinator.assert_called()
    
    @patch('src.agents.collaboration_manager.get_context_manager')
    def test_context_manager_integration(self, mock_get_context):
        """测试与上下文管理器的集成"""
        mock_context_manager = Mock()
        mock_get_context.return_value = mock_context_manager
        
        # 测试上下文相关的协作功能
        request = self.manager.create_collaboration_request(
            requesting_agent=AgentRole.PLANNER,
            target_agent=AgentRole.RESEARCHER,
            task_description="需要上下文的任务",
            required_capabilities=["上下文分析"],
            priority=1
        )
        
        # 验证上下文管理器被正确调用
        mock_get_context.assert_called()


def test_get_collaboration_manager():
    """测试获取协作管理器实例"""
    manager = get_collaboration_manager()
    assert isinstance(manager, CollaborationManager)
    
    # 验证单例模式
    manager2 = get_collaboration_manager()
    assert manager is manager2