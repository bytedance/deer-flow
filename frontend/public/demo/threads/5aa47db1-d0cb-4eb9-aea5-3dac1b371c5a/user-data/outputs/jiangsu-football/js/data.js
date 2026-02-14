// 江苏城市足球联赛2025赛季 - 数据文件

const leagueData = {
    // 联赛信息
    leagueInfo: {
        name: "江苏城市足球联赛",
        season: "2025赛季",
        alias: "苏超联赛第一季",
        teamsCount: 12,
        totalMatches: 132,
        weeks: 26,
        startDate: "2025-03-01",
        endDate: "2025-10-31"
    },

    // 参赛球队
    teams: [
        {
            id: 1,
            name: "南京城联",
            city: "南京",
            shortName: "NJL",
            colors: ["#dc2626", "#ef4444"],
            founded: 2020,
            stadium: "南京奥体中心",
            capacity: 62000,
            manager: "张伟",
            captain: "李明"
        },
        {
            id: 2,
            name: "苏州雄狮",
            city: "苏州",
            shortName: "SZS",
            colors: ["#059669", "#10b981"],
            founded: 2019,
            stadium: "苏州奥林匹克体育中心",
            capacity: 45000,
            manager: "王强",
            captain: "陈浩"
        },
        {
            id: 3,
            name: "无锡太湖",
            city: "无锡",
            shortName: "WXT",
            colors: ["#3b82f6", "#60a5fa"],
            founded: 2021,
            stadium: "无锡体育中心",
            capacity: 32000,
            manager: "赵刚",
            captain: "刘洋"
        },
        {
            id: 4,
            name: "常州龙城",
            city: "常州",
            shortName: "CZL",
            colors: ["#7c3aed", "#8b5cf6"],
            founded: 2022,
            stadium: "常州奥林匹克体育中心",
            capacity: 38000,
            manager: "孙磊",
            captain: "周涛"
        },
        {
            id: 5,
            name: "镇江金山",
            city: "镇江",
            shortName: "ZJJ",
            colors: ["#f59e0b", "#fbbf24"],
            founded: 2020,
            stadium: "镇江体育会展中心",
            capacity: 28000,
            manager: "吴斌",
            captain: "郑军"
        },
        {
            id: 6,
            name: "扬州运河",
            city: "扬州",
            shortName: "YZY",
            colors: ["#ec4899", "#f472b6"],
            founded: 2021,
            stadium: "扬州体育公园",
            capacity: 35000,
            manager: "钱勇",
            captain: "王磊"
        },
        {
            id: 7,
            name: "南通江海",
            city: "南通",
            shortName: "NTJ",
            colors: ["#0ea5e9", "#38bdf8"],
            founded: 2022,
            stadium: "南通体育会展中心",
            capacity: 32000,
            manager: "冯超",
            captain: "张勇"
        },
        {
            id: 8,
            name: "徐州楚汉",
            city: "徐州",
            shortName: "XZC",
            colors: ["#84cc16", "#a3e635"],
            founded: 2019,
            stadium: "徐州奥体中心",
            capacity: 42000,
            manager: "陈明",
            captain: "李强"
        },
        {
            id: 9,
            name: "淮安运河",
            city: "淮安",
            shortName: "HAY",
            colors: ["#f97316", "#fb923c"],
            founded: 2021,
            stadium: "淮安体育中心",
            capacity: 30000,
            manager: "周伟",
            captain: "吴刚"
        },
        {
            id: 10,
            name: "盐城黄海",
            city: "盐城",
            shortName: "YCH",
            colors: ["#06b6d4", "#22d3ee"],
            founded: 2020,
            stadium: "盐城体育中心",
            capacity: 32000,
            manager: "郑涛",
            captain: "孙明"
        },
        {
            id: 11,
            name: "泰州凤城",
            city: "泰州",
            shortName: "TZF",
            colors: ["#8b5cf6", "#a78bfa"],
            founded: 2022,
            stadium: "泰州体育公园",
            capacity: 28000,
            manager: "王刚",
            captain: "陈涛"
        },
        {
            id: 12,
            name: "宿迁西楚",
            city: "宿迁",
            shortName: "SQC",
            colors: ["#10b981", "#34d399"],
            founded: 2021,
            stadium: "宿迁体育中心",
            capacity: 26000,
            manager: "李伟",
            captain: "张刚"
        }
    ],

    // 积分榜数据
    standings: [
        {
            rank: 1,
            teamId: 1,
            played: 13,
            won: 8,
            drawn: 3,
            lost: 2,
            goalsFor: 24,
            goalsAgainst: 12,
            goalDifference: 12,
            points: 27
        },
        {
            rank: 2,
            teamId: 2,
            played: 13,
            won: 7,
            drawn: 4,
            lost: 2,
            goalsFor: 22,
            goalsAgainst: 14,
            goalDifference: 8,
            points: 25
        },
        {
            rank: 3,
            teamId: 8,
            played: 13,
            won: 7,
            drawn: 3,
            lost: 3,
            goalsFor: 20,
            goalsAgainst: 15,
            goalDifference: 5,
            points: 24
        },
        {
            rank: 4,
            teamId: 3,
            played: 13,
            won: 6,
            drawn: 4,
            lost: 3,
            goalsFor: 18,
            goalsAgainst: 14,
            goalDifference: 4,
            points: 22
        },
        {
            rank: 5,
            teamId: 4,
            played: 13,
            won: 6,
            drawn: 3,
            lost: 4,
            goalsFor: 19,
            goalsAgainst: 16,
            goalDifference: 3,
            points: 21
        },
        {
            rank: 6,
            teamId: 6,
            played: 13,
            won: 5,
            drawn: 5,
            lost: 3,
            goalsFor: 17,
            goalsAgainst: 15,
            goalDifference: 2,
            points: 20
        },
        {
            rank: 7,
            teamId: 5,
            played: 13,
            won: 5,
            drawn: 4,
            lost: 4,
            goalsFor: 16,
            goalsAgainst: 15,
            goalDifference: 1,
            points: 19
        },
        {
            rank: 8,
            teamId: 7,
            played: 13,
            won: 4,
            drawn: 5,
            lost: 4,
            goalsFor: 15,
            goalsAgainst: 16,
            goalDifference: -1,
            points: 17
        },
        {
            rank: 9,
            teamId: 10,
            played: 13,
            won: 4,
            drawn: 4,
            lost: 5,
            goalsFor: 14,
            goalsAgainst: 17,
            goalDifference: -3,
            points: 16
        },
        {
            rank: 10,
            teamId: 9,
            played: 13,
            won: 3,
            drawn: 5,
            lost: 5,
            goalsFor: 13,
            goalsAgainst: 18,
            goalDifference: -5,
            points: 14
        },
        {
            rank: 11,
            teamId: 11,
            played: 13,
            won: 2,
            drawn: 4,
            lost: 7,
            goalsFor: 11,
            goalsAgainst: 20,
            goalDifference: -9,
            points: 10
        },
        {
            rank: 12,
            teamId: 12,
            played: 13,
            won: 1,
            drawn: 3,
            lost: 9,
            goalsFor: 9,
            goalsAgainst: 24,
            goalDifference: -15,
            points: 6
        }
    ],

    // 赛程数据
    fixtures: [
        {
            id: 1,
            round: 1,
            date: "2025-03-01",
            time: "15:00",
            homeTeamId: 1,
            awayTeamId: 2,
            venue: "南京奥体中心",
            status: "completed",
            homeScore: 2,
            awayScore: 1
        },
        {
            id: 2,
            round: 1,
            date: "2025-03-01",
            time: "15:00",
            homeTeamId: 3,
            awayTeamId: 4,
            venue: "无锡体育中心",
            status: "completed",
            homeScore: 1,
            awayScore: 1
        },
        {
            id: 3,
            round: 1,
            date: "2025-03-02",
            time: "19:30",
            homeTeamId: 5,
            awayTeamId: 6,
            venue: "镇江体育会展中心",
            status: "completed",
            homeScore: 0,
            awayScore: 2
        },
        {
            id: 4,
            round: 1,
            date: "2025-03-02",
            time: "19:30",
            homeTeamId: 7,
            awayTeamId: 8,
            venue: "南通体育会展中心",
            status: "completed",
            homeScore: 1,
            awayScore: 3
        },
        {
            id: 5,
            round: 1,
            date: "2025-03-03",
            time: "15:00",
            homeTeamId: 9,
            awayTeamId: 10,
            venue: "淮安体育中心",
            status: "completed",
            homeScore: 2,
            awayScore: 2
        },
        {
            id: 6,
            round: 1,
            date: "2025-03-03",
            time: "15:00",
            homeTeamId: 11,
            awayTeamId: 12,
            venue: "泰州体育公园",
            status: "completed",
            homeScore: 1,
            awayScore: 0
        },
        {
            id: 7,
            round: 2,
            date: "2025-03-08",
            time: "15:00",
            homeTeamId: 2,
            awayTeamId: 3,
            venue: "苏州奥林匹克体育中心",
            status: "completed",
            homeScore: 2,
            awayScore: 0
        },
        {
            id: 8,
            round: 2,
            date: "2025-03-08",
            time: "15:00",
            homeTeamId: 4,
            awayTeamId: 5,
            venue: "常州奥林匹克体育中心",
            status: "completed",
            homeScore: 3,
            awayScore: 1
        },
        {
            id: 9,
            round: 2,
            date: "2025-03-09",
            time: "19:30",
            homeTeamId: 6,
            awayTeamId: 7,
            venue: "扬州体育公园",
            status: "completed",
            homeScore: 1,
            awayScore: 1
        },
        {
            id: 10,
            round: 2,
            date: "2025-03-09",
            time: "19:30",
            homeTeamId: 8,
            awayTeamId: 9,
            venue: "徐州奥体中心",
            status: "completed",
            homeScore: 2,
            awayScore: 0
        },
        {
            id: 11,
            round: 2,
            date: "2025-03-10",
            time: "15:00",
            homeTeamId: 10,
            awayTeamId: 11,
            venue: "盐城体育中心",
            status: "completed",
            homeScore: 1,
            awayScore: 0
        },
        {
            id: 12,
            round: 2,
            date: "2025-03-10",
            time: "15:00",
            homeTeamId: 12,
            awayTeamId: 1,
            venue: "宿迁体育中心",
            status: "completed",
            homeScore: 0,
            awayScore: 3
        },
        {
            id: 13,
            round: 12,
            date: "2025-05-24",
            time: "19:30",
            homeTeamId: 1,
            awayTeamId: 2,
            venue: "南京奥体中心",
            status: "scheduled"
        },
        {
            id: 14,
            round: 12,
            date: "2025-05-24",
            time: "15:00",
            homeTeamId: 3,
            awayTeamId: 4,
            venue: "无锡体育中心",
            status: "scheduled"
        },
        {
            id: 15,
            round: 12,
            date: "2025-05-25",
            time: "19:30",
            homeTeamId: 5,
            awayTeamId: 6,
            venue: "镇江体育会展中心",
            status: "scheduled"
        },
        {
            id: 16,
            round: 12,
            date: "2025-05-25",
            time: "15:00",
            homeTeamId: 7,
            awayTeamId: 8,
            venue: "南通体育会展中心",
            status: "scheduled"
        },
        {
            id: 17,
            round: 12,
            date: "2025-05-26",
            time: "19:30",
            homeTeamId: 9,
            awayTeamId: 10,
            venue: "淮安体育中心",
            status: "scheduled"
        },
        {
            id: 18,
            round: 12,
            date: "2025-05-26",
            time: "15:00",
            homeTeamId: 11,
            awayTeamId: 12,
            venue: "泰州体育公园",
            status: "scheduled"
        }
    ],

    // 球员数据
    players: {
        scorers: [
            {
                rank: 1,
                playerId: 101,
                name: "张伟",
                teamId: 1,
                goals: 12,
                assists: 4,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 2,
                playerId: 102,
                name: "李明",
                teamId: 1,
                goals: 8,
                assists: 6,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 3,
                playerId: 201,
                name: "王强",
                teamId: 2,
                goals: 7,
                assists: 5,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 4,
                playerId: 301,
                name: "赵刚",
                teamId: 3,
                goals: 6,
                assists: 3,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 5,
                playerId: 801,
                name: "陈明",
                teamId: 8,
                goals: 6,
                assists: 2,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 6,
                playerId: 401,
                name: "孙磊",
                teamId: 4,
                goals: 5,
                assists: 4,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 7,
                playerId: 601,
                name: "钱勇",
                teamId: 6,
                goals: 5,
                assists: 3,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 8,
                playerId: 501,
                name: "吴斌",
                teamId: 5,
                goals: 4,
                assists: 5,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 9,
                playerId: 701,
                name: "冯超",
                teamId: 7,
                goals: 4,
                assists: 3,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 10,
                playerId: 1001,
                name: "郑涛",
                teamId: 10,
                goals: 3,
                assists: 2,
                matches: 13,
                minutes: 1170
            }
        ],
        
        assists: [
            {
                rank: 1,
                playerId: 102,
                name: "李明",
                teamId: 1,
                assists: 6,
                goals: 8,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 2,
                playerId: 501,
                name: "吴斌",
                teamId: 5,
                assists: 5,
                goals: 4,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 3,
                playerId: 201,
                name: "王强",
                teamId: 2,
                assists: 5,
                goals: 7,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 4,
                playerId: 401,
                name: "孙磊",
                teamId: 4,
                assists: 4,
                goals: 5,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 5,
                playerId: 101,
                name: "张伟",
                teamId: 1,
                assists: 4,
                goals: 12,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 6,
                playerId: 301,
                name: "赵刚",
                teamId: 3,
                assists: 3,
                goals: 6,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 7,
                playerId: 601,
                name: "钱勇",
                teamId: 6,
                assists: 3,
                goals: 5,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 8,
                playerId: 701,
                name: "冯超",
                teamId: 7,
                assists: 3,
                goals: 4,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 9,
                playerId: 901,
                name: "周伟",
                teamId: 9,
                assists: 3,
                goals: 2,
                matches: 13,
                minutes: 1170
            },
            {
                rank: 10,
                playerId: 1101,
                name: "王刚",
                teamId: 11,
                assists: 2,
                goals: 1,
                matches: 13,
                minutes: 1170
            }
        ]
    },

    // 新闻数据
    news: [
        {
            id: 1,
            title: "南京城联主场力克苏州雄狮，继续领跑积分榜",
            excerpt: "在昨晚进行的第12轮焦点战中，南京城联凭借张伟的梅开二度，主场2-1战胜苏州雄狮，继续以2分优势领跑积分榜。",
            category: "比赛战报",
            date: "2025-05-25",
            imageColor: "#dc2626"
        },
        {
            id: 2,
            title: "联赛最佳球员揭晓：张伟当选4月最佳",
            excerpt: "江苏城市足球联赛官方宣布，南京城联前锋张伟凭借出色的表现，当选4月份联赛最佳球员。",
            category: "官方公告",
            date: "2025-05-20",
            imageColor: "#3b82f6"
        },
        {
            id: 3,
            title: "徐州楚汉签下前国脚李强，实力大增",
            excerpt: "徐州楚汉俱乐部官方宣布，与前国家队中场李强签约两年，这位经验丰富的老将将提升球队中场实力。",
            category: "转会新闻",
            date: "2025-05-18",
            imageColor: "#84cc16"
        },
        {
            id: 4,
            title: "联赛半程总结：竞争激烈，多队有望争冠",
            excerpt: "随着联赛进入半程，积分榜前六名球队分差仅7分，本赛季冠军争夺异常激烈，多支球队都有机会问鼎。",
            category: "联赛动态",
            date: "2025-05-15",
            imageColor: "#f59e0b"
        },
        {
            id: 5,
            title: "球迷互动日：各俱乐部将举办开放训练",
            excerpt: "为感谢球迷支持，各俱乐部将在本周末举办球迷开放日，球迷可近距离观看球队训练并与球员互动。",
            category: "球迷活动",
            date: "2025-05-12",
            imageColor: "#ec4899"
        },
        {
            id: 6,
            title: "技术统计：联赛进球数创历史新高",
            excerpt: "本赛季前13轮共打进176球，场均2.77球，创下联赛历史同期最高进球纪录，进攻足球成为主流。",
            category: "数据统计",
            date: "2025-05-10",
            imageColor: "#0ea5e9"
        }
    ]
};

// 工具函数：根据ID获取球队信息
function getTeamById(teamId) {
    return leagueData.teams.find(team => team.id === teamId);
}

// 工具函数：格式化日期
function formatDate(dateString) {
    const date = new Date(dateString);
    const options = { weekday: 'short', month: 'short', day: 'numeric' };
    return date.toLocaleDateString('zh-CN', options);
}

// 工具函数：格式化时间
function formatTime(timeString) {
    return timeString;
}

// 导出数据
if (typeof module !== 'undefined' && module.exports) {
    module.exports = leagueData;
}