export default function PrivacyPage() {
  return (
    <div className="container-md mx-auto px-4 py-24">
      <h1 className="mb-6 text-3xl font-bold tracking-tight">隐私政策</h1>
      <div className="text-muted-foreground space-y-4 text-sm leading-relaxed">
        <p>最后更新日期：2026 年 6 月 4 日</p>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          一、信息收集
        </h2>
        <p>
          EHM AI 工作台（以下简称"本平台"）由沈阳因思科技有限公司（以下简称"我们"）运营。我们收集的必要信息包括：用户登录凭证、对话记录、以及设备健康管理相关的业务数据。所有数据存储于您指定的服务器环境中。
        </p>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          二、信息使用
        </h2>
        <p>我们使用收集的信息用于以下目的：</p>
        <ul className="list-disc pl-6 space-y-1">
          <li>提供和维护 AI 驱动的设备健康管理服务</li>
          <li>生成监测报告、诊断分析和预警通知</li>
          <li>改善平台功能和用户体验</li>
        </ul>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          三、Cookie 使用
        </h2>
        <p>
          本平台使用必要的会话 Cookie 以维持用户登录状态和个性化设置。我们不使用第三方跟踪 Cookie。您可以通过浏览器设置管理 Cookie。
        </p>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          四、数据安全
        </h2>
        <p>
          我们采取合理的技术和管理措施保护您的数据安全。因工业场景的特殊性，建议您在私有化部署环境中使用本平台，以确保数据完全受控于您的网络边界内。
        </p>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          五、联系我们
        </h2>
        <p>
          如对本隐私政策有任何疑问，请通过电子邮件联系我们：support@inscphm.com。
        </p>
      </div>
    </div>
  );
}
