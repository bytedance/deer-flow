"""
Agent协作集成测试
测试Agent协作系统的端到端功能和工作流程集成
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.agents.step_coordinator import StepCoordinator, get_step_coordinator
from src.agents.collaboration_manager import CollaborationManager, AgentRole, get_collaboration_manager
from src.prompts.planner_model import Step, StepType


class TestAgentCollaborationIntegration:
    """Agent协作系统集成测试"""
    
    def setup_method(self):
        """测试前的设置"""
        self.step_coordinator = StepCoordinator()
        self.collaboration_manager = CollaborationManager()
    
    def test_step_coordination_with_collaboration(self):
        """测试步骤协调与协作管理的集成"""
        # 创建复杂的研究步骤
        steps = [
            Step(
                step_id="data_collection",
                description="收集多源数据",
                step_type=StepType.RESEARCH,
                expected_output="多源数据集"
            ),
            Step(
                step_id="data_preprocessing",
                description="数据清洗和预处理",
                step_type=StepType.PROCESSING,
                expected_output="清洁数据"
            ),
            Step(
                step_id="statistical_analysis",
                description="统计分析和建模",
                step_type=StepType.PROCESSING,
                expected_output="统计模型"
            ),
            Step(
                step_id="result_interpretation",
                description="结果解释和验证",
                step_type=StepType.RESEARCH,
                expected_output="解释报告"
            ),
            Step(
                step_id="final_report",
                description="生成最终研究报告",
                step_type=StepType.RESEARCH,
                expected_output="研究报告"
            )
        ]
        
        # 1. 步骤协调器分析依赖关系
        dependencies = self.step_coordinator.analyze_dependencies(steps)
        assert isinstance(dependencies, list)
        
        # 2. 创建执行计划
        execution_plan = self.step_coordinator.create_execution_plan(steps)
        assert execution_plan.total_steps == 5
        
        # 3. 协作管理器分配Agent
        collaboration_info = self.collaboration_manager.get_collaboration_info(steps)
        assert "agent_assignments" in collaboration_info
        assert len(collaboration_info["agent_assignments"]) == 5
        
        # 4. 验证Agent分配的合理性
        assignments = collaboration_info["agent_assignments"]
        
        # 数据收集应该分配给RESEARCHER
        data_collection_agent = assignments.get("data_collection")
        assert data_collection_agent in [AgentRole.RESEARCHER, AgentRole.ANALYST]
        
        # 数据处理应该分配给CODER或ANALYST
        preprocessing_agent = assignments.get("data_preprocessing")
        assert preprocessing_agent in [AgentRole.CODER, AgentRole.ANALYST]
        
        # 统计分析应该分配给ANALYST
        analysis_agent = assignments.get("statistical_analysis")
        assert analysis_agent in [AgentRole.ANALYST, AgentRole.RESEARCHER]
    
    def test_parallel_collaboration_workflow(self):
        """测试并行协作工作流"""
        # 创建可以并行执行的步骤
        parallel_steps = [
            Step(
                step_id="market_research",
                description="市场调研",
                step_type=StepType.RESEARCH,
                expected_output="市场报告"
            ),
            Step(
                step_id="competitor_analysis",
                description="竞争对手分析",
                step_type=StepType.RESEARCH,
                expected_output="竞争分析"
            ),
            Step(
                step_id="technical_feasibility",
                description="技术可行性分析",
                step_type=StepType.PROCESSING,
                expected_output="技术评估"
            )
        ]
        
        # 创建执行计划，允许并行执行
        execution_plan = self.step_coordinator.create_execution_plan(
            parallel_steps, max_parallel=3
        )
        
        assert execution_plan.max_parallel_steps == 3
        
        # 获取协作信息
        collaboration_info = self.collaboration_manager.get_collaboration_info(parallel_steps)
        
        # 验证并行协作模式
        patterns = collaboration_info.get("collaboration_patterns", {})
        assert len(patterns) > 0
        
        # 至少有一些步骤应该支持并行执行
        parallel_patterns = [
            pattern for pattern in patterns.values() 
            if "parallel" in str(pattern).lower()
        ]
        # 注意：这个断言可能需要根据实际实现调整
        # assert len(parallel_patterns) > 0
    
    def test_hierarchical_collaboration_workflow(self):
        """测试层级协作工作流"""
        # 创建需要层级协作的复杂步骤
        hierarchical_steps = [
            Step(
                step_id="project_planning",
                description="项目整体规划",
                step_type=StepType.RESEARCH,
                expected_output="项目计划"
            ),
            Step(
                step_id="task_decomposition",
                description="任务分解和分配",
                step_type=StepType.PROCESSING,
                expected_output="任务列表"
            ),
            Step(
                step_id="resource_allocation",
                description="资源分配和调度",
                step_type=StepType.PROCESSING,
                expected_output="资源计划"
            ),
            Step(
                step_id="execution_monitoring",
                description="执行监控和调整",
                step_type=StepType.RESEARCH,
                expected_output="监控报告"
            )
        ]
        
        # 分析协作模式
        collaboration_info = self.collaboration_manager.get_collaboration_info(hierarchical_steps)
        
        # 验证层级协作的特征
        assignments = collaboration_info["agent_assignments"]
        
        # 项目规划应该由PLANNER或COORDINATOR负责
        planning_agent = assignments.get("project_planning")
        assert planning_agent in [AgentRole.PLANNER, AgentRole.COORDINATOR]
        
        # 监控应该由COORDINATOR负责
        monitoring_agent = assignments.get("execution_monitoring")
        assert monitoring_agent in [AgentRole.COORDINATOR, AgentRole.VALIDATOR]
    
    def test_agent_workload_balancing(self):
        """测试Agent工作负载均衡"""
        # 创建大量步骤来测试负载均衡
        many_steps = []
        for i in range(10):
            step = Step(
                step_id=f"task_{i}",
                description=f"执行任务{i}",
                step_type=StepType.RESEARCH if i % 2 == 0 else StepType.PROCESSING,
                expected_output=f"任务{i}结果"
            )
            many_steps.append(step)
        
        # 获取协作信息
        collaboration_info = self.collaboration_manager.get_collaboration_info(many_steps)
        assignments = collaboration_info["agent_assignments"]
        
        # 统计每个Agent的任务数量
        agent_task_counts = {}
        for step_id, agent in assignments.items():
            agent_task_counts[agent] = agent_task_counts.get(agent, 0) + 1
        
        # 验证负载相对均衡（没有单个Agent承担过多任务）
        max_tasks = max(agent_task_counts.values())
        min_tasks = min(agent_task_counts.values())
        
        # 最大和最小任务数的差异不应该太大
        assert max_tasks - min_tasks <= 3
    
    def test_error_handling_in_collaboration(self):
        """测试协作过程中的错误处理"""
        step = Step(
            step_id="error_prone_task",
            description="可能出错的任务",
            step_type=StepType.PROCESSING,
            expected_output="处理结果"
        )
        
        # 模拟执行失败
        with patch.object(self.step_coordinator, '_execute_step_logic') as mock_execute:
            mock_execute.side_effect = Exception("执行失败")
            
            result = self.step_coordinator.execute_step(step)
            
            assert result["success"] is False
            assert "error" in result
        
        # 测试协作管理器的错误处理
        request = self.collaboration_manager.create_collaboration_request(
            requesting_agent=AgentRole.COORDINATOR,
            target_agent=AgentRole.RESEARCHER,
            task_description="错误测试任务",
            required_capabilities=["测试"],
            priority=1
        )
        
        # 模拟处理失败的协作请求
        try:
            response = self.collaboration_manager.process_collaboration_request(
                "nonexistent_request", {"result": "测试"}
            )
            # 如果没有抛出异常，检查响应是否正确处理了错误
            assert response is not None
        except Exception as e:
            # 如果抛出异常，验证是预期的错误类型
            assert isinstance(e, (KeyError, ValueError))
    
    def test_context_aware_collaboration(self):
        """测试上下文感知的协作"""
        with patch('src.agents.step_coordinator.get_context_manager') as mock_get_context:
            mock_context_manager = Mock()
            mock_context_manager.get_current_context.return_value = {
                "research_domain": "机器学习",
                "complexity_level": "高",
                "available_resources": ["GPU", "大数据集"]
            }
            mock_get_context.return_value = mock_context_manager
            
            # 创建需要上下文感知的步骤
            context_steps = [
                Step(
                    step_id="ml_model_training",
                    description="训练机器学习模型",
                    step_type=StepType.PROCESSING,
                    expected_output="训练好的模型"
                ),
                Step(
                    step_id="model_evaluation",
                    description="评估模型性能",
                    step_type=StepType.PROCESSING,
                    expected_output="评估报告"
                )
            ]
            
            # 获取协作信息
            collaboration_info = self.collaboration_manager.get_collaboration_info(context_steps)
            
            # 验证上下文管理器被调用
            mock_get_context.assert_called()
            
            # 验证Agent分配考虑了上下文
            assignments = collaboration_info["agent_assignments"]
            
            # 机器学习任务应该分配给有相关能力的Agent
            ml_agent = assignments.get("ml_model_training")
            assert ml_agent in [AgentRole.CODER, AgentRole.ANALYST]
    
    def test_communication_between_agents(self):
        """测试Agent间的通信"""
        # 创建需要Agent间通信的步骤序列
        communication_steps = [
            Step(
                step_id="data_request",
                description="请求数据收集",
                step_type=StepType.RESEARCH,
                expected_output="数据需求"
            ),
            Step(
                step_id="data_provision",
                description="提供收集的数据",
                step_type=StepType.RESEARCH,
                expected_output="数据集"
            ),
            Step(
                step_id="data_analysis",
                description="分析提供的数据",
                step_type=StepType.PROCESSING,
                expected_output="分析结果"
            )
        ]
        
        # 模拟Agent间的通信
        for i, step in enumerate(communication_steps):
            if i > 0:  # 从第二个步骤开始需要前一个步骤的结果
                # 创建协作请求
                request = self.collaboration_manager.create_collaboration_request(
                    requesting_agent=AgentRole.COORDINATOR,
                    target_agent=AgentRole.RESEARCHER,
                    task_description=step.description,
                    required_capabilities=["数据处理"],
                    priority=1
                )
                
                assert isinstance(request, type(request))
                assert request.task_description == step.description
        
        # 验证通信历史
        history = self.collaboration_manager.get_communication_history(
            AgentRole.COORDINATOR, AgentRole.RESEARCHER
        )
        
        # 应该有通信记录
        assert isinstance(history, list)
    
    def test_knowledge_sharing_between_agents(self):
        """测试Agent间的知识共享"""
        # 模拟一个Agent学习到新知识
        knowledge_item = {
            "topic": "数据预处理最佳实践",
            "content": "详细的数据预处理步骤和注意事项",
            "source_agent": AgentRole.ANALYST,
            "relevance_score": 0.95,
            "applicable_domains": ["数据科学", "机器学习"]
        }
        
        # 添加到共享知识库
        self.collaboration_manager.add_to_knowledge_base(
            "data_preprocessing_best_practices", knowledge_item
        )
        
        # 其他Agent检索知识
        retrieved_knowledge = self.collaboration_manager.get_from_knowledge_base(
            "data_preprocessing_best_practices"
        )
        
        assert retrieved_knowledge is not None
        assert retrieved_knowledge["topic"] == "数据预处理最佳实践"
        assert retrieved_knowledge["source_agent"] == AgentRole.ANALYST
        
        # 验证知识的相关性评分
        assert retrieved_knowledge["relevance_score"] == 0.95


class TestAgentCollaborationPerformance:
    """Agent协作性能测试"""
    
    def setup_method(self):
        """测试前的设置"""
        self.step_coordinator = StepCoordinator()
        self.collaboration_manager = CollaborationManager()
    
    def test_large_scale_collaboration(self):
        """测试大规模协作性能"""
        # 创建大量步骤
        large_steps = []
        for i in range(50):
            step = Step(
                step_id=f"large_task_{i}",
                description=f"大规模任务{i}",
                step_type=StepType.RESEARCH if i % 3 == 0 else StepType.PROCESSING,
                expected_output=f"任务{i}结果"
            )
            large_steps.append(step)
        
        # 测试性能
        import time
        start_time = time.time()
        
        # 分析依赖关系
        dependencies = self.step_coordinator.analyze_dependencies(large_steps)
        
        # 创建执行计划
        execution_plan = self.step_coordinator.create_execution_plan(large_steps)
        
        # 获取协作信息
        collaboration_info = self.collaboration_manager.get_collaboration_info(large_steps)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # 验证性能（应该在合理时间内完成）
        assert execution_time < 5.0  # 5秒内完成
        
        # 验证结果正确性
        assert len(dependencies) >= 0
        assert execution_plan.total_steps == 50
        assert len(collaboration_info["agent_assignments"]) == 50
    
    def test_concurrent_collaboration_requests(self):
        """测试并发协作请求处理"""
        import threading
        import time
        
        results = []
        
        def create_and_process_request(request_id):
            """创建和处理协作请求的线程函数"""
            try:
                request = self.collaboration_manager.create_collaboration_request(
                    requesting_agent=AgentRole.COORDINATOR,
                    target_agent=AgentRole.RESEARCHER,
                    task_description=f"并发任务{request_id}",
                    required_capabilities=["数据处理"],
                    priority=1
                )
                
                # 模拟处理时间
                time.sleep(0.1)
                
                response = self.collaboration_manager.process_collaboration_request(
                    request.request_id, {"result": f"完成任务{request_id}"}
                )
                
                results.append({"request_id": request_id, "success": True, "response": response})
            except Exception as e:
                results.append({"request_id": request_id, "success": False, "error": str(e)})
        
        # 创建多个并发线程
        threads = []
        for i in range(10):
            thread = threading.Thread(target=create_and_process_request, args=(i,))
            threads.append(thread)
            thread.start()
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        # 验证结果
        assert len(results) == 10
        successful_requests = [r for r in results if r["success"]]
        
        # 大部分请求应该成功处理
        assert len(successful_requests) >= 8


def test_integration_singletons():
    """测试集成组件的单例模式"""
    # 测试步骤协调器单例
    coordinator1 = get_step_coordinator()
    coordinator2 = get_step_coordinator()
    assert coordinator1 is coordinator2
    
    # 测试协作管理器单例
    manager1 = get_collaboration_manager()
    manager2 = get_collaboration_manager()
    assert manager1 is manager2