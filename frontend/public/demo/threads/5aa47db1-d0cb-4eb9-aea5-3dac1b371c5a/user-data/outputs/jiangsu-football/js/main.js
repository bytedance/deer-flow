// 江苏城市足球联赛2025赛季 - 主JavaScript文件

document.addEventListener('DOMContentLoaded', function() {
    // 初始化加载动画
    initLoader();
    
    // 初始化主题切换
    initThemeToggle();
    
    // 初始化导航菜单
    initNavigation();
    
    // 初始化滚动监听
    initScrollSpy();
    
    // 渲染球队卡片
    renderTeams();
    
    // 渲染积分榜
    renderStandings();
    
    // 渲染赛程表
    renderFixtures();
    
    // 渲染数据统计
    renderStats();
    
    // 渲染新闻动态
    renderNews();
    
    // 初始化标签页切换
    initTabs();
    
    // 初始化移动端菜单
    initMobileMenu();
});

// 加载动画
function initLoader() {
    const loader = document.querySelector('.loader');
    
    // 模拟加载延迟
    setTimeout(() => {
        loader.classList.add('loaded');
        
        // 动画结束后隐藏loader
        setTimeout(() => {
            loader.style.display = 'none';
        }, 300);
    }, 1500);
}

// 主题切换
function initThemeToggle() {
    const themeToggle = document.querySelector('.btn-theme-toggle');
    const themeIcon = themeToggle.querySelector('i');
    
    // 检查本地存储的主题偏好
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);
    
    themeToggle.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        updateThemeIcon(newTheme);
        
        // 添加切换动画
        themeToggle.style.transform = 'scale(0.9)';
        setTimeout(() => {
            themeToggle.style.transform = '';
        }, 150);
    });
    
    function updateThemeIcon(theme) {
        if (theme === 'dark') {
            themeIcon.className = 'fas fa-sun';
        } else {
            themeIcon.className = 'fas fa-moon';
        }
    }
}

// 导航菜单
function initNavigation() {
    const navLinks = document.querySelectorAll('.nav-link');
    
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href');
            const targetSection = document.querySelector(targetId);
            
            if (targetSection) {
                // 更新活动链接
                navLinks.forEach(l => l.classList.remove('active'));
                this.classList.add('active');
                
                // 平滑滚动到目标区域
                window.scrollTo({
                    top: targetSection.offsetTop - 80,
                    behavior: 'smooth'
                });
                
                // 如果是移动端，关闭菜单
                const navMenu = document.querySelector('.nav-menu');
                if (navMenu.classList.contains('active')) {
                    navMenu.classList.remove('active');
                }
            }
        });
    });
}

// 滚动监听
function initScrollSpy() {
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-link');
    
    window.addEventListener('scroll', () => {
        let current = '';
        
        sections.forEach(section => {
            const sectionTop = section.offsetTop;
            const sectionHeight = section.clientHeight;
            
            if (scrollY >= sectionTop - 100) {
                current = section.getAttribute('id');
            }
        });
        
        navLinks.forEach(link => {
            link.classList.remove('active');
            if (link.getAttribute('href') === `#${current}`) {
                link.classList.add('active');
            }
        });
    });
}

// 渲染球队卡片
function renderTeams() {
    const teamsGrid = document.querySelector('.teams-grid');
    
    if (!teamsGrid) return;
    
    teamsGrid.innerHTML = '';
    
    leagueData.teams.forEach(team => {
        const teamCard = document.createElement('div');
        teamCard.className = 'team-card';
        
        // 获取球队统计数据
        const standing = leagueData.standings.find(s => s.teamId === team.id);
        
        teamCard.innerHTML = `
            <div class="team-card-logo" style="background: linear-gradient(135deg, ${team.colors[0]} 0%, ${team.colors[1]} 100%);">
                ${team.shortName}
            </div>
            <h3 class="team-card-name">${team.name}</h3>
            <div class="team-card-city">${team.city}</div>
            <div class="team-card-stats">
                <div class="team-stat">
                    <div class="team-stat-value">${standing ? standing.rank : '-'}</div>
                    <div class="team-stat-label">排名</div>
                </div>
                <div class="team-stat">
                    <div class="team-stat-value">${standing ? standing.points : '0'}</div>
                    <div class="team-stat-label">积分</div>
                </div>
                <div class="team-stat">
                    <div class="team-stat-value">${standing ? standing.goalDifference : '0'}</div>
                    <div class="team-stat-label">净胜球</div>
                </div>
            </div>
        `;
        
        teamCard.addEventListener('click', () => {
            // 这里可以添加点击跳转到球队详情页的功能
            alert(`查看 ${team.name} 的详细信息`);
        });
        
        teamsGrid.appendChild(teamCard);
    });
}

// 渲染积分榜
function renderStandings() {
    const standingsTable = document.querySelector('.standings-table tbody');
    
    if (!standingsTable) return;
    
    standingsTable.innerHTML = '';
    
    leagueData.standings.forEach(standing => {
        const team = getTeamById(standing.teamId);
        
        const row = document.createElement('tr');
        
        // 根据排名添加特殊样式
        if (standing.rank <= 4) {
            row.classList.add('champions-league');
        } else if (standing.rank <= 6) {
            row.classList.add('europa-league');
        } else if (standing.rank >= 11) {
            row.classList.add('relegation');
        }
        
        row.innerHTML = `
            <td>${standing.rank}</td>
            <td>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <div class="team-logo-small" style="width: 24px; height: 24px; border-radius: 50%; background: linear-gradient(135deg, ${team.colors[0]} 0%, ${team.colors[1]} 100%);"></div>
                    ${team.name}
                </div>
            </td>
            <td>${standing.played}</td>
            <td>${standing.won}</td>
            <td>${standing.drawn}</td>
            <td>${standing.lost}</td>
            <td>${standing.goalsFor}</td>
            <td>${standing.goalsAgainst}</td>
            <td>${standing.goalDifference > 0 ? '+' : ''}${standing.goalDifference}</td>
            <td><strong>${standing.points}</strong></td>
        `;
        
        standingsTable.appendChild(row);
    });
}

// 渲染赛程表
function renderFixtures() {
    const fixturesList = document.querySelector('.fixtures-list');
    
    if (!fixturesList) return;
    
    fixturesList.innerHTML = '';
    
    // 按轮次分组
    const fixturesByRound = {};
    leagueData.fixtures.forEach(fixture => {
        if (!fixturesByRound[fixture.round]) {
            fixturesByRound[fixture.round] = [];
        }
        fixturesByRound[fixture.round].push(fixture);
    });
    
    // 渲染所有赛程
    Object.keys(fixturesByRound).sort((a, b) => a - b).forEach(round => {
        const roundHeader = document.createElement('div');
        roundHeader.className = 'fixture-round-header';
        roundHeader.innerHTML = `<h3>第${round}轮</h3>`;
        fixturesList.appendChild(roundHeader);
        
        fixturesByRound[round].forEach(fixture => {
            const homeTeam = getTeamById(fixture.homeTeamId);
            const awayTeam = getTeamById(fixture.awayTeamId);
            
            const fixtureItem = document.createElement('div');
            fixtureItem.className = 'fixture-item';
            
            const date = new Date(fixture.date);
            const dayNames = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
            const dayName = dayNames[date.getDay()];
            
            let scoreHtml = '';
            let statusText = '';
            
            if (fixture.status === 'completed') {
                scoreHtml = `
                    <div class="fixture-score-value">${fixture.homeScore} - ${fixture.awayScore}</div>
                    <div class="fixture-score-status">已结束</div>
                `;
            } else if (fixture.status === 'scheduled') {
                scoreHtml = `
                    <div class="fixture-score-value">VS</div>
                    <div class="fixture-score-status">${fixture.time}</div>
                `;
            } else {
                scoreHtml = `
                    <div class="fixture-score-value">-</div>
                    <div class="fixture-score-status">待定</div>
                `;
            }
            
            fixtureItem.innerHTML = `
                <div class="fixture-date">
                    <div class="fixture-day">${dayName}</div>
                    <div class="fixture-time">${formatDate(fixture.date)}</div>
                </div>
                <div class="fixture-teams">
                    <div class="fixture-team home">
                        <div class="fixture-team-name">${homeTeam.name}</div>
                        <div class="fixture-team-logo" style="background: linear-gradient(135deg, ${homeTeam.colors[0]} 0%, ${homeTeam.colors[1]} 100%);"></div>
                    </div>
                    <div class="fixture-vs">VS</div>
                    <div class="fixture-team away">
                        <div class="fixture-team-logo" style="background: linear-gradient(135deg, ${awayTeam.colors[0]} 0%, ${awayTeam.colors[1]} 100%);"></div>
                        <div class="fixture-team-name">${awayTeam.name}</div>
                    </div>
                </div>
                <div class="fixture-score">
                    ${scoreHtml}
                </div>
            `;
            
            fixturesList.appendChild(fixtureItem);
        });
    });
}

// 渲染数据统计
function renderStats() {
    renderScorers();
    renderAssists();
    renderTeamStats();
}

function renderScorers() {
    const scorersContainer = document.querySelector('#scorers');
    
    if (!scorersContainer) return;
    
    scorersContainer.innerHTML = `
        <table class="stats-table">
            <thead>
                <tr>
                    <th class="stats-rank">排名</th>
                    <th class="stats-player">球员</th>
                    <th class="stats-team">球队</th>
                    <th class="stats-value">进球</th>
                    <th class="stats-value">助攻</th>
                    <th class="stats-value">出场</th>
                </tr>
            </thead>
            <tbody>
                ${leagueData.players.scorers.map(player => {
                    const team = getTeamById(player.teamId);
                    return `
                        <tr>
                            <td class="stats-rank">${player.rank}</td>
                            <td class="stats-player">${player.name}</td>
                            <td class="stats-team">${team.name}</td>
                            <td class="stats-value">${player.goals}</td>
                            <td class="stats-value">${player.assists}</td>
                            <td class="stats-value">${player.matches}</td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
}

function renderAssists() {
    const assistsContainer = document.querySelector('#assists');
    
    if (!assistsContainer) return;
    
    assistsContainer.innerHTML = `
        <table class="stats-table">
            <thead>
                <tr>
                    <th class="stats-rank">排名</th>
                    <th class="stats-player">球员</th>
                    <th class="stats-team">球队</th>
                    <th class="stats-value">助攻</th>
                    <th class="stats-value">进球</th>
                    <th class="stats-value">出场</th>
                </tr>
            </thead>
            <tbody>
                ${leagueData.players.assists.map(player => {
                    const team = getTeamById(player.teamId);
                    return `
                        <tr>
                            <td class="stats-rank">${player.rank}</td>
                            <td class="stats-player">${player.name}</td>
                            <td class="stats-team">${team.name}</td>
                            <td class="stats-value">${player.assists}</td>
                            <td class="stats-value">${player.goals}</td>
                            <td class="stats-value">${player.matches}</td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
}

function renderTeamStats() {
    const teamStatsContainer = document.querySelector('#teams');
    
    if (!teamStatsContainer) return;
    
    // 计算球队统计数据
    const teamStats = leagueData.standings.map(standing => {
        const team = getTeamById(standing.teamId);
        const goalsPerGame = (standing.goalsFor / standing.played).toFixed(2);
        const concededPerGame = (standing.goalsAgainst / standing.played).toFixed(2);
        
        return {
            rank: standing.rank,
            team: team.name,
            goalsFor: standing.goalsFor,
            goalsAgainst: standing.goalsAgainst,
            goalDifference: standing.goalDifference,
            goalsPerGame,
            concededPerGame,
            cleanSheets: Math.floor(Math.random() * 5) // 模拟数据
        };
    }).sort((a, b) => a.rank - b.rank);
    
    teamStatsContainer.innerHTML = `
        <table class="stats-table">
            <thead>
                <tr>
                    <th class="stats-rank">排名</th>
                    <th class="stats-player">球队</th>
                    <th class="stats-value">进球</th>
                    <th class="stats-value">失球</th>
                    <th class="stats-value">净胜球</th>
                    <th class="stats-value">场均进球</th>
                    <th class="stats-value">场均失球</th>
                    <th class="stats-value">零封</th>
                </tr>
            </thead>
            <tbody>
                ${teamStats.map(stat => `
                    <tr>
                        <td class="stats-rank">${stat.rank}</td>
                        <td class="stats-player">${stat.team}</td>
                        <td class="stats-value">${stat.goalsFor}</td>
                        <td class="stats-value">${stat.goalsAgainst}</td>
                        <td class="stats-value">${stat.goalDifference > 0 ? '+' : ''}${stat.goalDifference}</td>
                        <td class="stats-value">${stat.goalsPerGame}</td>
                        <td class="stats-value">${stat.concededPerGame}</td>
                        <td class="stats-value">${stat.cleanSheets}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

// 渲染新闻动态
function renderNews() {
    const newsGrid = document.querySelector('.news-grid');
    
    if (!newsGrid) return;
    
    newsGrid.innerHTML = '';
    
    leagueData.news.forEach(newsItem => {
        const newsCard = document.createElement('div');
        newsCard.className = 'news-card';
        
        const date = new Date(newsItem.date);
        const formattedDate = date.toLocaleDateString('zh-CN', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
        
        newsCard.innerHTML = `
            <div class="news-card-image" style="background: linear-gradient(135deg, ${newsItem.imageColor} 0%, ${darkenColor(newsItem.imageColor, 20)} 100%);"></div>
            <div class="news-card-content">
                <span class="news-card-category">${newsItem.category}</span>
                <h3 class="news-card-title">${newsItem.title}</h3>
                <p class="news-card-excerpt">${newsItem.excerpt}</p>
                <div class="news-card-meta">
                    <span class="news-card-date">
                        <i class="far fa-calendar"></i>
                        ${formattedDate}
                    </span>
                    <span class="news-card-read-more">阅读更多 →</span>
                </div>
            </div>
        `;
        
        newsCard.addEventListener('click', () => {
            alert(`查看新闻: ${newsItem.title}`);
        });
        
        newsGrid.appendChild(newsCard);
    });
}

// 初始化标签页切换
function initTabs() {
    // 赛程标签页
    const fixtureTabs = document.querySelectorAll('.fixtures-tabs .tab');
    const fixtureItems = document.querySelectorAll('.fixture-item');
    
    fixtureTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // 更新活动标签
            fixtureTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            const roundFilter = tab.getAttribute('data-round');
            
            // 这里可以根据筛选条件显示不同的赛程
            // 由于时间关系，这里只是简单的演示
            console.log(`筛选赛程: ${roundFilter}`);
        });
    });
    
    // 数据统计标签页
    const statsTabs = document.querySelectorAll('.stats-tab');
    const statsContents = document.querySelectorAll('.stats-tab-content');
    
    statsTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabId = tab.getAttribute('data-tab');
            
            // 更新活动标签
            statsTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            // 显示对应内容
            statsContents.forEach(content => {
                content.classList.remove('active');
                if (content.id === tabId) {
                    content.classList.add('active');
                }
            });
        });
    });
}

// 初始化移动端菜单
function initMobileMenu() {
    const menuToggle = document.querySelector('.btn-menu-toggle');
    const navMenu = document.querySelector('.nav-menu');
    
    if (menuToggle && navMenu) {
        menuToggle.addEventListener('click', () => {
            navMenu.classList.toggle('active');
            
            // 更新菜单图标
            const icon = menuToggle.querySelector('i');
            if (navMenu.classList.contains('active')) {
                icon.className = 'fas fa-times';
            } else {
                icon.className = 'fas fa-bars';
            }
        });
        
        // 点击菜单外区域关闭菜单
        document.addEventListener('click', (e) => {
            if (!navMenu.contains(e.target) && !menuToggle.contains(e.target)) {
                navMenu.classList.remove('active');
                menuToggle.querySelector('i').className = 'fas fa-bars';
            }
        });
    }
}

// 工具函数：加深颜色
function darkenColor(color, percent) {
    const num = parseInt(color.replace("#", ""), 16);
    const amt = Math.round(2.55 * percent);
    const R = (num >> 16) - amt;
    const G = (num >> 8 & 0x00FF) - amt;
    const B = (num & 0x0000FF) - amt;
    
    return "#" + (
        0x1000000 +
        (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 +
        (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 +
        (B < 255 ? B < 1 ? 0 : B : 255)
    ).toString(16).slice(1);
}

// 工具函数：格式化日期（简写）
function formatDate(dateString) {
    const date = new Date(dateString);
    const month = date.getMonth() + 1;
    const day = date.getDate();
    return `${month}月${day}日`;
}

// 工具函数：根据ID获取球队信息
function getTeamById(teamId) {
    return leagueData.teams.find(team => team.id === teamId);
}

// 添加一些交互效果
document.addEventListener('DOMContentLoaded', () => {
    // 为所有按钮添加点击效果
    const buttons = document.querySelectorAll('.btn');
    buttons.forEach(button => {
        button.addEventListener('mousedown', () => {
            button.style.transform = 'scale(0.95)';
        });
        
        button.addEventListener('mouseup', () => {
            button.style.transform = '';
        });
        
        button.addEventListener('mouseleave', () => {
            button.style.transform = '';
        });
    });
    
    // 为卡片添加悬停效果
    const cards = document.querySelectorAll('.team-card, .news-card');
    cards.forEach(card => {
        card.addEventListener('mouseenter', () => {
            card.style.transition = 'transform 0.3s ease, box-shadow 0.3s ease';
        });
    });
});