from pathlib import Path

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import BrowserAssets, PluginContribution

from .gateway import build_router
from .timing import TimingOptions, TimingRepository


@extension(api="0.2.3", name="trajectory")
def install(registry, config):
    repository = TimingRepository(options=TimingOptions(config.get("timing")))
    registry.routers((build_router(repository),))
    if (
        registry.plugin(
            PluginContribution(
                namespace="community.trajectory",
                title="运行轨迹 / Trajectory",
                description="展示主子 agent 轨迹、工具及模型完整响应耗时，定位慢步骤、失败与重试线索。",
                enabled=True,
                frontend=BrowserAssets("trajectory.v1", Path(__file__).parent),
            )
        )
        is not True
    ):
        raise RuntimeError("此插件需要宿主支持全栈插件契约")
    if repository.options.enabled:
        from .middleware import TimingContributor

        registry.middlewares(TimingContributor(repository))
