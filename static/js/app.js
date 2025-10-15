document.addEventListener('DOMContentLoaded', () => {
    // --- GLOBAL STATE & CONFIG ---
    const BASE_URL = 'http://127.0.0.1:5001';
    const appState = { isLoggedIn: false, user: null, features: [], charts: { main: null, eda: {} } };

    // --- API CLIENT ---
    async function api(endpoint, options = {}) {
        try {
            const response = await fetch(`${BASE_URL}/api${endpoint}`, options);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || errorData.error || 'An API error occurred');
            }
            const contentType = response.headers.get("content-type");
            if (contentType && contentType.includes("application/json")) {
                return response.json();
            }
            return { success: true, message: 'Operation successful' };
        } catch (error) {
            showFlash(error.message, 'danger');
            throw error;
        }
    }

    // --- CORE UI ---
    function showFlash(message, category = 'info') {
        const colors = { success: 'bg-green-100 text-green-800', danger: 'bg-red-100 text-red-800', info: 'bg-blue-100 text-blue-800' };
        const alert = document.createElement('div');
        alert.className = `p-4 mb-2 text-sm rounded-lg shadow-lg transition-all duration-300 transform translate-x-10 opacity-0 ${colors[category]}`;
        alert.textContent = message;
        document.getElementById('flash-container').appendChild(alert);
        setTimeout(() => { alert.classList.remove('translate-x-10'); alert.classList.add('translate-x-0', 'opacity-100'); }, 10);
        setTimeout(() => { alert.style.opacity = 0; setTimeout(() => alert.remove(), 500); }, 4500);
    }

    function updateNav() {
        const navLinks = document.getElementById('nav-links');
        if (!navLinks) return;
        
        navLinks.innerHTML = appState.isLoggedIn 
            ? `<a class="hidden sm:block text-slate-600 hover:text-violet-600 font-semibold" href="/dashboard">Dashboard</a>
               <a class="hidden sm:block text-slate-600 hover:text-violet-600 font-semibold" href="/profile">Profile</a>
               <a id="logout-btn" class="btn btn-secondary cursor-pointer">Logout</a>`
            : `<a class="hidden sm:block text-slate-600 hover:text-violet-600 font-semibold" href="/dashboard">Dashboard</a>
               <a class="hidden sm:block text-slate-600 hover:text-violet-600 font-semibold" href="/login">Login</a>
               <a class="btn btn-primary" href="/register">Register</a>`;
        
        if (appState.isLoggedIn) {
            document.getElementById('logout-btn').addEventListener('click', handleLogout);
        }
    }
    
    // --- AUTHENTICATION HANDLERS ---
    async function handleLogin(e) {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
            const res = await api('/login', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
            if (res.success) {
                showFlash(res.message, 'success');
                window.location.href = '/dashboard'; // Redirect on success
            }
        } catch (error) {
            console.error("Login failed:", error);
        }
    }

    async function handleRegister(e) {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
            const res = await api('/register', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
            if (res.success) {
                showFlash(res.message, 'success');
                window.location.href = '/login'; // Redirect to login after registration
            }
        } catch (error) {
            console.error("Registration failed:", error);
        }
    }
    
    async function handleLogout(e) {
        e.preventDefault();
        try {
            await api('/logout', { method: 'POST' });
            showFlash('You have been logged out.', 'success');
            window.location.href = '/'; // Redirect to home page
        } catch (error) {
            console.error("Logout failed:", error);
        }
    }

    async function handleProfileUpdate(e) {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
            const res = await api('/profile', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
            if (res.success) {
                appState.user.age = res.user.age;
                appState.user.conditions = res.user.conditions;
                showFlash(res.message, 'success');
            }
        } catch (error) {
            console.error("Profile update failed:", error);
        }
    }
    
    function renderPredictionForm() {
        const container = document.getElementById('prediction-form');
        if (!container) return; // Only run on dashboard page
        const features = appState.features || [];
        if (features.length === 0) {
            container.innerHTML = `<p class="col-span-2 text-center text-sm text-red-500">Could not load prediction model features. Manual prediction is unavailable.</p>`;
            return;
        }
        const inputsHTML = features.map(f => `
            <div class="col-span-2 sm:col-span-1">
                <label for="manual-${f}" class="block text-xs font-medium text-slate-600">${f}</label>
                <input type="number" step="any" id="manual-${f}" name="${f}" required class="form-input text-sm mt-1">
            </div>
        `).join('');
        container.innerHTML = `<div class="grid grid-cols-2 gap-4">${inputsHTML}</div><button type="submit" class="w-full btn btn-secondary mt-4">Predict Manually</button>`;
    }

    // --- DASHBOARD: AQI DISPLAY & PREDICTION ---
    const getAqiInfo = (aqi) => {
        if (aqi === null || isNaN(aqi)) return { category: "Unknown", gradient: 'from-slate-400 to-slate-600' };
        const val = Math.round(aqi);
        if (val <= 50) return { category: "Good", gradient: 'from-green-400 to-teal-500' };
        if (val <= 100) return { category: "Moderate", gradient: 'from-yellow-400 to-amber-500' };
        if (val <= 150) return { category: "Unhealthy for Sensitive", gradient: 'from-orange-400 to-red-500' };
        if (val <= 200) return { category: "Unhealthy", gradient: 'from-red-500 to-rose-600' };
        if (val <= 300) return { category: "Very Unhealthy", gradient: 'from-purple-500 to-fuchsia-600' };
        return { category: "Hazardous", gradient: 'from-fuchsia-800 to-pink-900' };
    };
    
    function setAqiDisplay(state, data = null) {
        const displayCard = document.getElementById('aqi-main-display');
        let content = '', background = 'bg-slate-500';
        if (state === 'initial') {
            content = `<svg class="h-12 w-12 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg><p class="mt-4 text-lg font-semibold opacity-80">Ready for a Prediction</p><p class="text-sm opacity-70">Click the "Fetch & Predict" button to get the live AQI.</p>`;
        } else if (state === 'loading') {
            content = `<div class="loader"></div><p class="mt-4 text-lg font-semibold opacity-80">Fetching Live Data...</p>`;
        } else if (state === 'success' && data) {
            const aqiInfo = getAqiInfo(data.predicted_aqi);
            background = `bg-gradient-to-br ${aqiInfo.gradient}`;
            content = `<h2 class="text-lg font-semibold opacity-80 mb-2">Current Ambient AQI</h2><div class="text-7xl font-extrabold tracking-tighter">${Math.round(data.predicted_aqi)}${data.emoji || ''}</div><div class="text-2xl font-bold opacity-90">${data.category}</div><p class="mt-4 text-sm opacity-80 max-w-xs mx-auto">${data.advice}</p><div class="${data.perceived_aqi ? '' : 'hidden'} mt-4 pt-4 border-t border-white/20"><h3 class="text-md font-semibold opacity-80">Your Perceived AQI</h3><div class="text-4xl font-bold">${data.perceived_aqi ? Math.round(data.perceived_aqi) : '--'}</div></div>`;
            const personalAdviceSection = document.getElementById('personal-advice-section');
            if (appState.isLoggedIn && data.personal_advice) {
                personalAdviceSection.querySelector('#personal-advice-text').textContent = data.personal_advice;
                personalAdviceSection.style.display = 'flex';
            } else {
                personalAdviceSection.style.display = 'none';
            }
        }
        displayCard.className = `aqi-card-gradient p-6 rounded-2xl shadow-lg text-center text-white relative overflow-hidden min-h-[280px] flex flex-col justify-center items-center ${background}`;
        displayCard.innerHTML = content;
    }

    async function handleFetchAndPredict() {
        const statusEl = document.getElementById('fetch-status');
        statusEl.textContent = 'Fetching conditions...';
        setAqiDisplay('loading');
        try {
            const result = await api('/fetch_current_data');
            const features = {};
            for (const key in result.data) {
                if ((appState.features || []).includes(key)) {
                    features[key] = result.data[key];
                    const inputEl = document.getElementById(`manual-${key}`);
                    if(inputEl) inputEl.value = result.data[key];
                }
            }
            statusEl.textContent = 'Predicting with live data...';
            const predResult = await api('/predict', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(features) });
            setAqiDisplay('success', predResult);
            statusEl.textContent = 'Live prediction complete!';
        } catch (e) {
            statusEl.textContent = `Error: ${e.message}`;
            setAqiDisplay('initial');
        }
    }

    async function handlePrediction(e) {
        e.preventDefault();
        setAqiDisplay('loading');
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
            const predResult = await api('/predict', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
            setAqiDisplay('success', predResult);
            showFlash('Manual prediction successful!', 'success');
        } catch (e) {
            setAqiDisplay('initial');
        }
    }
    
    // --- DASHBOARD: FORECAST & CHARTS ---
    function initializeMainChart() {
        const ctx = document.getElementById('aqiChart').getContext('2d');
        if (appState.charts.main) appState.charts.main.destroy();
        appState.charts.main = new Chart(ctx, { type: 'line', options: { responsive: true, maintainAspectRatio: false, scales: { x: { type: 'time', time: { unit: 'hour' } }, y: { beginAtZero: true } }, plugins: { legend: { display: false } } } });
    }

    function updateMainChart(historical, forecast) {
        const chart = appState.charts.main;
        const datasets = [{ label: 'Historical AQI', data: historical.map(d => ({x: d.ds, y: d.yhat})), borderColor: '#a78bfa', borderWidth: 3, pointRadius: 0, tension: 0.4, fill: true, backgroundColor: 'rgba(167, 139, 250, 0.1)' }];
        if (forecast?.length > 0) {
            datasets.push({ label: 'Forecasted AQI', data: forecast.map(d => ({x: d.ds, y: d.yhat})), borderColor: '#6366f1', borderWidth: 2, borderDash: [5, 5], pointRadius: 0, tension: 0.4 });
            if (appState.isLoggedIn && forecast.some(d => d.perceived_yhat !== null)) {
                datasets.push({ label: 'Perceived AQI', data: forecast.map(d => ({x: d.ds, y: d.perceived_yhat})), borderColor: '#ec4899', borderWidth: 2, borderDash: [5, 5], pointRadius: 0, tension: 0.4 });
            }
        }
        chart.data.datasets = datasets;
        chart.update();
    }

    async function handleForecast(e) {
        e.preventDefault();
        const hours = document.getElementById('hours').value;
        showFlash('Generating forecast...', 'info');
        try {
            const d = await api('/forecast_lstm', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ hours }) });
            updateMainChart(d.historical, d.forecast);
            renderForecastTable(d.forecast);
        } catch (e) {}
    }
    
    function renderForecastTable(forecastData) {
        const container = document.getElementById('forecast-table-container');
        if (!forecastData || forecastData.length === 0) { container.classList.add('hidden'); return; }
        const tableHead = container.querySelector('thead');
        const tableBody = container.querySelector('tbody');
        let headHTML = '<tr><th class="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase">Time</th><th class="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase">Ambient AQI</th>';
        if (appState.isLoggedIn && forecastData.some(d => d.perceived_yhat !== null)) headHTML += '<th class="px-6 py-3 text-left text-xs font-medium text-red-500 uppercase">Perceived AQI</th>';
        headHTML += '<th class="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase">Category</th></tr>';
        tableHead.innerHTML = headHTML;
        const getCategory = (aqi) => {const val=Math.round(aqi);if(val<=50)return "Good";if(val<=100)return "Moderate";if(val<=150)return "Sensitive";if(val<=200)return "Unhealthy";if(val<=300)return "Very Unhealthy";return "Hazardous"};
        tableBody.innerHTML = forecastData.map(item => {
            const date = new Date(item.ds);
            let perceivedCell = (appState.isLoggedIn && item.perceived_yhat !== null) ? `<td class="px-6 py-4 text-sm font-bold text-red-500">${Math.round(item.perceived_yhat)}</td>` : (appState.isLoggedIn ? `<td class="px-6 py-4 text-sm">-</td>` : '');
            return `<tr><td class="px-6 py-4 text-sm">${date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</td><td class="px-6 py-4 font-bold">${Math.round(item.yhat)}</td>${perceivedCell}<td class="px-6 py-4">${getCategory(item.yhat)}</td></tr>`;
        }).join('');
        container.classList.remove('hidden');
    }

    // --- EDA MODAL LOGIC ---
    function setupEdaTabs() {
        const tabs = {'timeseries': 'Time Series', 'trends': 'Trends', 'datatable': 'Data Table'};
        const tabContainer = document.getElementById('eda-tabs');
        tabContainer.innerHTML = Object.entries(tabs).map(([key, value]) => `<button data-tab="${key}" class="eda-tab">${value}</button>`).join('');
        tabContainer.addEventListener('click', (e) => { if (e.target.matches('.eda-tab')) showEdaTab(e.target.dataset.tab) });
    }
    function showEdaTab(tabId) {
        document.querySelectorAll('#eda-tabs .eda-tab').forEach(tab => tab.classList.toggle('active', tab.dataset.tab === tabId));
        document.querySelectorAll('.eda-tab-content').forEach(content => content.classList.toggle('active', content.id === `eda-tab-${tabId}`));
    }
    function destroyEdaCharts() { Object.values(appState.charts.eda).forEach(chart => chart?.destroy()); appState.charts.eda = {}; }
    function renderEdaTable(tableData) {
        const container = document.getElementById('eda-data-table');
        if (!tableData || !tableData.data || tableData.data.length === 0) { container.innerHTML = '<p class="text-center text-slate-400">No data to display.</p>'; return; }
        const head = tableData.columns.map(col => `<th class="p-2 sticky top-0 bg-slate-700 font-semibold">${col}</th>`).join('');
        const body = tableData.data.map(row => `<tr>${tableData.columns.map(col => `<td class="p-2 border-t border-slate-700">${(col === 'Datetime') ? new Date(row[col]).toLocaleString() : (row[col] ?? '-')}</td>`).join('')}</tr>`).join('');
        container.innerHTML = `<table class="w-full text-left whitespace-nowrap"><thead><tr>${head}</tr></thead><tbody class="text-slate-300">${body}</tbody></table>`;
    }
    function createEdaCharts(data) {
        destroyEdaCharts();
        const chartOpts = { responsive: true, maintainAspectRatio: false, color: '#94a3b8', plugins: { legend: { labels: { color: '#94a3b8' } } }, scales: { x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(148, 163, 184, 0.2)' } }, y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(148, 163, 184, 0.2)' } } } };
        const { time_series: tsData, deep_dive: ddData, table_data: tableData } = data;
        renderEdaTable(tableData);
        document.getElementById('stats-cards').innerHTML = `<div class="bg-slate-700 p-4 rounded-lg"><p class="text-sm">Average</p><p class="text-2xl font-bold">${tsData.stats.mean ?? 'N/A'}</p></div><div class="bg-slate-700 p-4 rounded-lg"><p class="text-sm">Median</p><p class="text-2xl font-bold">${tsData.stats.median ?? 'N/A'}</p></div><div class="bg-slate-700 p-4 rounded-lg"><p class="text-sm">Max</p><p class="text-2xl font-bold text-red-400">${tsData.stats.max ?? 'N/A'}</p></div><div class="bg-slate-700 p-4 rounded-lg"><p class="text-sm">Min</p><p class="text-2xl font-bold text-green-400">${tsData.stats.min ?? 'N/A'}</p></div>`;
        appState.charts.eda.aqiOverTime = new Chart(document.getElementById('aqiOverTimeChart'), { type: 'line', data: { labels: tsData.aqi_over_time.labels, datasets: [{ label: 'Daily Average AQI', data: tsData.aqi_over_time.values, borderColor: '#8b5cf6', tension: 0.1 }] }, options: { ...chartOpts, scales: { ...chartOpts.scales, x: { type: 'time', time: { unit: 'day' } } } } });
        const catColors = { "Good":"#28a745", "Moderate":"#ffc107", "Unhealthy for Sensitive Groups":"#fd7e14", "Unhealthy":"#dc3545", "Very Unhealthy":"#8f3e97", "Hazardous":"#7f0000" };
        appState.charts.eda.categoryPie = new Chart(document.getElementById('categoryPieChart'), { type: 'pie', data: { labels: tsData.categories.labels, datasets: [{ data: tsData.categories.values, backgroundColor: tsData.categories.labels.map(l => catColors[l] || '#808080') }] }, options: { ...chartOpts, scales: {} } });
        appState.charts.eda.dist = new Chart(document.getElementById('distChart'), { type: 'bar', data: { labels: tsData.dist.labels, datasets: [{ label: 'Frequency (Hours)', data: tsData.dist.values, backgroundColor: '#4299e1' }] }, options: chartOpts });
        appState.charts.eda.byMonth = new Chart(document.getElementById('byMonthChart'), { type: 'bar', data: { labels: ddData.by_month.labels, datasets: [{ label: 'Avg AQI', data: ddData.by_month.values, backgroundColor: '#6366f1' }] }, options: chartOpts });
        appState.charts.eda.byDayOfWeek = new Chart(document.getElementById('byDayOfWeekChart'), { type: 'bar', data: { labels: ddData.by_day_of_week.labels, datasets: [{ label: 'Avg AQI', data: ddData.by_day_of_week.values, backgroundColor: '#a78bfa' }] }, options: chartOpts });
        appState.charts.eda.byHour = new Chart(document.getElementById('byHourChart'), { type: 'bar', data: { labels: ddData.by_hour.labels, datasets: [{ label: 'Avg AQI', data: ddData.by_hour.values, backgroundColor: '#ec4899' }] }, options: chartOpts });
    }
    async function runAnalysis() {
        const start = document.getElementById('start-date').value, end = document.getElementById('end-date').value;
        if (!start || !end) return showFlash('Please select both dates.', 'danger');
        const loader = document.getElementById('eda-loader'), content = document.getElementById('eda-content'), errorEl = document.getElementById('eda-error');
        loader.style.display = 'flex'; content.style.display = 'none'; errorEl.style.display = 'none';
        try {
            const data = await api(`/eda_data?start=${start}&end=${end}`);
            createEdaCharts(data);
            content.style.display = 'block';
            showEdaTab('timeseries');
        } catch (e) {
            errorEl.textContent = `Error: ${e.message}`; errorEl.style.display = 'block';
        } finally {
            loader.style.display = 'none';
        }
    }

    // --- PAGE SPECIFIC SETUP ---
    function initializeDashboard() {
        document.getElementById('fetch-conditions-btn').addEventListener('click', handleFetchAndPredict);
        document.getElementById('prediction-form').addEventListener('submit', handlePrediction);
        document.getElementById('forecast-form').addEventListener('submit', handleForecast);
        document.getElementById('toggle-manual-form').addEventListener('click', () => {
            document.getElementById('prediction-form-container').classList.toggle('hidden');
            document.getElementById('manual-form-arrow').classList.toggle('rotate-180');
        });
        document.getElementById('eda-btn').addEventListener('click', () => { 
            document.getElementById('eda-modal').classList.add('flex'); 
            document.getElementById('eda-modal').classList.remove('hidden'); 
            runAnalysis(); 
        });
        document.getElementById('close-eda-modal').addEventListener('click', () => { 
            document.getElementById('eda-modal').classList.remove('flex'); 
            document.getElementById('eda-modal').classList.add('hidden'); 
        });
        document.getElementById('run-analysis-btn').addEventListener('click', runAnalysis);

        const endDate = new Date(), startDate = new Date();
        startDate.setFullYear(endDate.getFullYear() - 1);
        document.getElementById('start-date').valueAsDate = startDate;
        document.getElementById('end-date').valueAsDate = endDate;

        setupEdaTabs();
        initializeMainChart();
        setAqiDisplay('initial');
        
        renderPredictionForm();
        
        api('/historical_data').then(data => {
            updateMainChart(data, []);
        }).catch(error => console.error("Initial chart data failed", error));
    }
    
    // --- MAIN INITIALIZATION ---
    async function init() {
        try {
            const session = await api('/session_status');
            appState.features = session.features || [];
            if (session.logged_in) {
                appState.isLoggedIn = true;
                appState.user = session.user;
            }
        } catch (error) {
            console.error("Session check failed, proceeding as logged out.");
        } finally {
            updateNav();
        }

        // --- PAGE-SPECIFIC INITIALIZATIONS ---
        if (document.getElementById('aqiChart')) {
            initializeDashboard();
        }
        const loginForm = document.getElementById('login-form');
        if (loginForm) {
            loginForm.addEventListener('submit', handleLogin);
        }
        const registerForm = document.getElementById('register-form');
        if (registerForm) {
            registerForm.addEventListener('submit', handleRegister);
        }
        const profileForm = document.getElementById('profile-form');
        if (profileForm && appState.isLoggedIn) {
            document.getElementById('profile-age').value = appState.user.age || '';
            document.getElementById('profile-conditions').value = appState.user.conditions || '';
            profileForm.addEventListener('submit', handleProfileUpdate);
        }
    }
    
    init();
});