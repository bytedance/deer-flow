export default function TermsPage() {
  return (
    <div className="container-md mx-auto px-4 py-24">
      <h1 className="mb-6 text-3xl font-bold tracking-tight">服务条款</h1>
      <div className="text-muted-foreground space-y-4 text-sm leading-relaxed">
        <p>最后更新日期：2026 年 6 月 4 日</p>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          一、服务说明
        </h2>
        <p>
          EHM AI 工作台（以下简称"本平台"）是深圳因思科技有限公司提供的工业设备健康管理软件即服务（SaaS）平台。本平台提供 AI 驱动的实时监测、故障诊断、运行报告生成等功能，面向石油石化行业用户。
        </p>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          二、使用许可
        </h2>
        <p>
          在遵守本条款的前提下，我们授予您一项非排他性、不可转让的许可，允许您在本平台授权范围内使用本服务。您不得对本平台进行反向工程、复制或再分发。
        </p>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          三、用户义务
        </h2>
        <ul className="list-disc pl-6 space-y-1">
          <li>妥善保管您的账户信息和登录凭证</li>
          <li>遵守适用的法律法规，不得利用本平台从事违法活动</li>
          <li>确保您上传的数据具有合法来源和授权</li>
        </ul>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          四、免责声明
        </h2>
        <p>
          本平台提供的 AI 分析结果和建议仅供参考，不构成最终的工程决策依据。对于因使用本平台信息而导致的任何直接或间接损失，我们不对其承担责任。关键设备操作和维修决策应由持证专业人员根据实际情况做出。
        </p>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          五、服务变更与终止
        </h2>
        <p>
          我们保留随时修改或终止服务的权利。重大变更将通过平台公告提前通知。您可通过停止使用本平台来终止本协议。
        </p>

        <h2 className="mt-8 mb-3 text-lg font-semibold text-foreground">
          六、联系我们
        </h2>
        <p>
          如对本服务条款有任何疑问，请通过电子邮件联系我们：support@inscphm.com。
        </p>
      </div>
    </div>
  );
}
