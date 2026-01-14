const { createApp, ref, onMounted } = Vue;

const JobsWidget = {
    setup() {
        const jobs = ref([]);
        const isConnected = ref(false);
        const botId = window.botId;

        const connect = () => {
            if (!botId) return;
            // Determine protocol (ws or wss)
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/${botId}`;

            console.log("Connecting to WS:", wsUrl);
            const ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                console.log("WS Connected");
                isConnected.value = true;
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'job_update' && data.job) {
                        updateJob(data.job);
                    }
                } catch (e) {
                    console.error("WS Message Parse Error", e);
                }
            };

            ws.onclose = () => {
                console.log("WS Closed, reconnecting...");
                isConnected.value = false;
                setTimeout(connect, 3000);
            };

            ws.onerror = (err) => {
                console.error("WS Error:", err);
                ws.close();
            };
        };

        const updateJob = (job) => {
            const index = jobs.value.findIndex(j => j.id === job.id);

            if (index !== -1) {
                // Update existing
                jobs.value[index] = { ...jobs.value[index], ...job };

                // If completed/failed, remove after delay
                if (['completed', 'failed'].includes(job.status)) {
                    setTimeout(() => {
                        jobs.value = jobs.value.filter(j => j.id !== job.id);
                    }, 5000);
                }
            } else if (['processing', 'pending', 'queued'].includes(job.status)) {
                // Add new if active
                jobs.value.push(job);
            }
        };

        // Initial fetch to populate (since WS only gives updates)
        const fetchJobs = async () => {
            if (!botId) return;
            try {
                const res = await fetch('/api/jobs/active');
                if (res.ok) {
                    const initialJobs = await res.json();
                    jobs.value = initialJobs;
                }
            } catch (e) { console.error("Initial jobs fetch error:", e); }
        };

        onMounted(() => {
            if (botId) {
                fetchJobs();
                connect();
            }
        });

        return { jobs, isConnected };
    },
    template: `
        <div v-if="jobs.length > 0" class="mt-4 px-3 fade-in">
             <div class="d-flex align-items-center justify-content-between mb-2">
                <small class="text-uppercase fw-bold" style="font-size: 0.65rem; color: #64748b; letter-spacing: 0.05em;">
                    Активные задачи
                </small>
                <div v-if="isConnected" class="spinner-grow text-primary" role="status" style="width: 0.4rem; height: 0.4rem; animation-duration: 2s;" title="Real-time connection active"></div>
                <div v-else class="text-danger" style="font-size: 0.6rem;" title="Disconnected">OFF</div>
            </div>
            <div class="d-flex flex-column gap-2 mb-3">
                <div v-for="job in jobs" :key="job.id" class="job-item p-2 rounded" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05);">
                    <div class="d-flex justify-content-between mb-1" style="font-size: 0.7rem;">
                        <span class="text-white opacity-75 text-truncate" style="max-width: 100px;">
                            {{ job.type === 'import_promo' ? 'Импорт' : (job.type === 'broadcast' ? 'Рассылка' : job.type) }}
                        </span>
                        <span class="text-primary fw-bold">{{ job.progress }}%</span>
                    </div>
                    <div class="progress" style="height: 3px; background: rgba(255,255,255,0.1);">
                        <div class="progress-bar bg-primary transition-width" :style="{width: job.progress + '%'}"></div>
                    </div>
                    <div v-if="job.details && job.details.processed !== undefined" class="mt-1 text-end" style="font-size: 0.6rem; color: #64748b;">
                        {{ job.details.processed }} / {{ job.details.total_lines || '?' }}
                    </div>
                </div>
            </div>
        </div>
    `
};

if (document.getElementById('vue-jobs-widget')) {
    createApp(JobsWidget).mount('#vue-jobs-widget');
}
