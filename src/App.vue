<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import type { Meeting } from './ics'
import { loadAgenda } from './ics'
import { startJitsiMeeting, type JitsiExternalAPI } from './jitsi'

const ICS_URL = import.meta.env.VITE_ICS_URL || '/calendar.ics'
const REFRESH_INTERVAL_MS = 60_000
const NOW_TICK_MS = 10_000
const DISPLAY_NAME = 'Salle de Réunion'
const FORCE_PAGE_RELOAD = !import.meta.env.VITE_ICS_URL

const events = ref<Meeting[]>([])
const agendaError = ref<string | null>(null)
const lastUpdated = ref<Date | null>(null)
const now = ref(new Date())

const activeMeeting = ref<Meeting | null>(null)
const isJoining = ref(false)
const joinError = ref<string | null>(null)
const jitsiApi = ref<JitsiExternalAPI | null>(null)
const jitsiContainer = ref<HTMLDivElement | null>(null)

const isInMeeting = computed(() => activeMeeting.value !== null)
const currentMeeting = computed(() => getCurrentMeeting(events.value, now.value))
const nextMeeting = computed(() => getNextMeeting(events.value, now.value))
const agendaPreview = computed(() =>
  events.value.filter((event) => event.end > now.value).slice(0, 6),
)

const dayFormatter = new Intl.DateTimeFormat('fr-FR', { weekday: 'long', month: 'long', day: 'numeric' })
const timeFormatter = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' })
const clockFormatter = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' })
const stampFormatter = new Intl.DateTimeFormat('fr-FR', {
  hour: '2-digit',
  minute: '2-digit',
  day: '2-digit',
  month: '2-digit',
})

let nowTimer: number | undefined
let refreshTimer: number | undefined

onMounted(() => {
  nowTimer = window.setInterval(() => (now.value = new Date()), NOW_TICK_MS)

  if (!ICS_URL) {
    agendaError.value = 'Définir VITE_ICS_URL dans un fichier .env.local'
    return
  }

  fetchAgenda()
  refreshTimer = window.setInterval(() => {
    if (isInMeeting.value) return

    if (FORCE_PAGE_RELOAD) {
      window.location.reload()
    } else {
      void fetchAgenda()
    }
  }, REFRESH_INTERVAL_MS)
})

onUnmounted(() => {
  if (nowTimer) {
    window.clearInterval(nowTimer)
  }

  if (refreshTimer) {
    window.clearInterval(refreshTimer)
  }

  teardownJitsi()
})

async function fetchAgenda() {
  if (!ICS_URL) return

  agendaError.value = null

  try {
    const snapshot = await loadAgenda(ICS_URL, new Date())
    events.value = snapshot.events
    lastUpdated.value = new Date()
  } catch (error) {
    agendaError.value =
      error instanceof Error ? error.message : 'Erreur inconnue lors du chargement du calendrier'
  }
}

async function joinMeeting(meeting: Meeting) {
  isJoining.value = true
  joinError.value = null

  try {
    if (!meeting.conferenceUrl) {
      throw new Error('Aucun lien Jitsi dans X-CONFERENCE ou DESCRIPTION')
    }

    // Bascule en vue "meeting" puis attends que le DOM rende le conteneur
    activeMeeting.value = meeting
    await nextTick()

    const container = jitsiContainer.value
    if (!container) {
      throw new Error('Zone d’affichage Jitsi introuvable')
    }

    teardownJitsi()
    container.innerHTML = ''

    const { domain, roomName } = parseJitsiUrl(meeting.conferenceUrl)

    const api = await startJitsiMeeting({
      domain,
      roomName,
      parentNode: container,
      userInfo: { displayName: DISPLAY_NAME },
      onConferenceLeft: handleConferenceEnded,
      onReadyToClose: handleConferenceEnded,
    })

    jitsiApi.value = api
  } catch (error) {
    joinError.value =
      error instanceof Error ? error.message : 'Impossible de lancer la conférence Jitsi'
    activeMeeting.value = null
  } finally {
    isJoining.value = false
  }
}

function handleConferenceEnded() {
  teardownJitsi()
  activeMeeting.value = null
  void fetchAgenda()
}

function teardownJitsi() {
  if (jitsiApi.value) {
    jitsiApi.value.dispose()
    jitsiApi.value = null
  }

  if (jitsiContainer.value) {
    jitsiContainer.value.innerHTML = ''
  }
}

function getCurrentMeeting(all: Meeting[], date: Date) {
  return all.find((event) => date >= event.start && date < event.end)
}

function getNextMeeting(all: Meeting[], date: Date) {
  return all.find((event) => event.start > date)
}

function parseJitsiUrl(conferenceUrl: string) {
  let parsed: URL

  try {
    parsed = new URL(conferenceUrl)
  } catch {
    throw new Error('URL Jitsi invalide')
  }

  const roomName = parsed.pathname.split('/').filter(Boolean).join('/')

  if (!roomName) {
    throw new Error('Impossible de déterminer la salle Jitsi')
  }

  return {
    domain: parsed.origin,
    roomName,
  }
}

function formatRange(meeting: Meeting) {
  return `${timeFormatter.format(meeting.start)} – ${timeFormatter.format(meeting.end)}`
}
</script>

<template>
  <div class="app-shell" :class="{ 'meeting-mode': isInMeeting }">
    <header class="top-bar">
      <div>
        <p class="eyebrow">Salle de réunion</p>
        <h1>Tableau Jitsi</h1>
        <p class="subtitle">Agenda ICS et lancement Jitsi via IFrame API</p>
      </div>
      <div class="top-meta">
        <p class="meta-line">
          <span class="dot live"></span>
          <span>{{ clockFormatter.format(now) }}</span>
        </p>
        <p v-if="lastUpdated" class="meta-line">MAJ {{ stampFormatter.format(lastUpdated) }}</p>
      </div>
    </header>

    <div v-if="agendaError" class="alert error">{{ agendaError }}</div>
    <div v-if="joinError" class="alert warning">{{ joinError }}</div>

    <section v-if="!isInMeeting" class="grid">
      <article class="panel current">
        <div class="panel-head">
          <div>
            <p class="label">Réunion en cours</p>
            <h2 v-if="currentMeeting">{{ currentMeeting.summary }}</h2>
            <h2 v-else>Aucune réunion</h2>
          </div>
          <span v-if="currentMeeting" class="badge live">En cours</span>
          <span v-else class="badge muted">Libre</span>
        </div>

        <div v-if="currentMeeting">
          <p class="time-range">
            {{ dayFormatter.format(currentMeeting.start) }} · {{ formatRange(currentMeeting) }}
          </p>
          <p v-if="currentMeeting.description" class="description">{{ currentMeeting.description }}</p>
          <div class="actions">
            <button class="primary" type="button" :disabled="isJoining || !currentMeeting.conferenceUrl"
              @click="joinMeeting(currentMeeting)">
              {{ isJoining ? 'Connexion…' : 'Rejoindre' }}
            </button>
            <span v-if="!currentMeeting.conferenceUrl" class="helper">Lien Jitsi absent</span>
          </div>
        </div>
        <p v-else class="placeholder">Pas d'événement en cours.</p>
      </article>

      <article class="panel next">
        <div class="panel-head">
          <div>
            <p class="label">Prochaine réunion</p>
            <h2 v-if="nextMeeting">{{ nextMeeting.summary }}</h2>
            <h2 v-else>Pas de réunion à venir</h2>
          </div>
          <span v-if="nextMeeting" class="badge upcoming">À venir</span>
        </div>

        <div v-if="nextMeeting">
          <p class="time-range">
            {{ dayFormatter.format(nextMeeting.start) }} · {{ formatRange(nextMeeting) }}
          </p>
          <p v-if="nextMeeting.description" class="description">{{ nextMeeting.description }}</p>
          <div class="actions">
            <button class="secondary" type="button" :disabled="isJoining || !nextMeeting.conferenceUrl"
              @click="joinMeeting(nextMeeting)">
              Préparer
            </button>
            <span v-if="!nextMeeting.conferenceUrl" class="helper">Lien Jitsi absent</span>
          </div>
        </div>
        <p v-else class="placeholder">Agenda libre après la réunion actuelle.</p>
      </article>

      <article class="panel agenda">
        <div class="panel-head">
          <div>
            <p class="label">Agenda</p>
            <h2>À venir</h2>
          </div>
        </div>
        <ul class="agenda-list">
          <li v-for="event in agendaPreview" :key="event.uid" class="agenda-item">
            <div class="agenda-time">
              <p class="agenda-day">{{ dayFormatter.format(event.start) }}</p>
              <p class="agenda-range">{{ formatRange(event) }}</p>
            </div>
            <div class="agenda-body">
              <p class="agenda-title">{{ event.summary }}</p>
              <p v-if="event.description" class="agenda-description">{{ event.description }}</p>
              <p v-if="event.location" class="agenda-location">{{ event.location }}</p>
            </div>
          </li>
          <li v-if="agendaPreview.length === 0" class="agenda-item empty">Aucun événement.</li>
        </ul>
      </article>
    </section>

    <section v-else class="meeting-view">
      <div ref="jitsiContainer" class="jitsi-frame"></div>
    </section>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  color: #e2e8f0;
}

.app-shell.meeting-mode {
  padding: 0;
  max-width: 100vw;
}

.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  padding: 1.25rem 1.5rem;
  border-radius: 18px;
  background: linear-gradient(120deg, #0f172a, #111827);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
}

.top-meta {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.meta-line {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.95rem;
  color: #cbd5e1;
}

.eyebrow {
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-size: 0.75rem;
  color: #8b9bb9;
  margin-bottom: 0.25rem;
}

h1 {
  font-size: 1.75rem;
  margin: 0;
  color: #f8fafc;
}

.subtitle {
  color: #a5b4fc;
  margin-top: 0.25rem;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
}

.panel {
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 18px;
  padding: 1.25rem 1.5rem;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25);
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
}

.panel h2 {
  margin: 0.1rem 0;
}

.label {
  font-size: 0.85rem;
  color: #94a3b8;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.65rem;
  border-radius: 999px;
  font-size: 0.8rem;
  background: rgba(255, 255, 255, 0.06);
  color: #cbd5e1;
}

.badge.live {
  background: rgba(74, 222, 128, 0.15);
  color: #4ade80;
  border: 1px solid rgba(74, 222, 128, 0.4);
}

.badge.upcoming {
  background: rgba(125, 211, 252, 0.12);
  color: #7dd3fc;
  border: 1px solid rgba(125, 211, 252, 0.35);
}

.badge.muted {
  background: rgba(226, 232, 240, 0.1);
  color: #cbd5e1;
}

.time-range {
  color: #cbd5e1;
  margin-bottom: 0.5rem;
}

.description {
  color: #94a3b8;
  margin-bottom: 0.75rem;
  line-height: 1.5;
}

.actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.primary,
.secondary {
  border: none;
  border-radius: 12px;
  padding: 0.65rem 1.1rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.15s ease, opacity 0.15s ease;
}

.primary {
  background: linear-gradient(120deg, #3b82f6, #6366f1);
  color: #f8fafc;
}

.secondary {
  background: rgba(255, 255, 255, 0.08);
  color: #f8fafc;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.primary:disabled,
.secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.primary:not(:disabled):hover,
.secondary:not(:disabled):hover {
  transform: translateY(-1px);
}

.helper {
  color: #94a3b8;
  font-size: 0.9rem;
}

.placeholder {
  color: #94a3b8;
  margin: 0.5rem 0 0;
}

.agenda {
  grid-column: span 2;
}

.agenda-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.agenda-item {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 0.5rem;
  padding: 0.75rem 0.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.agenda-item:last-child {
  border-bottom: none;
}

.agenda-item.empty {
  grid-template-columns: 1fr;
  color: #94a3b8;
}

.agenda-time {
  color: #cbd5e1;
}

.agenda-day {
  text-transform: capitalize;
}

.agenda-range {
  color: #a5b4fc;
}

.agenda-title {
  color: #e2e8f0;
  font-weight: 600;
}

.agenda-description,
.agenda-location {
  color: #94a3b8;
}

.meeting-view {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: #0b1224;
  border-radius: 0;
  padding: 0;
}

.jitsi-frame {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: #0b1224;
}

.alert {
  padding: 0.8rem 1rem;
  border-radius: 12px;
  color: #0b1224;
  font-weight: 600;
}

.alert.error {
  background: #fecdd3;
  border: 1px solid #fb7185;
}

.alert.warning {
  background: #fef3c7;
  border: 1px solid #fbbf24;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
}

.dot.live {
  background: #22c55e;
  box-shadow: 0 0 12px rgba(34, 197, 94, 0.6);
}

@media (max-width: 768px) {
  .agenda {
    grid-column: span 1;
  }

  .agenda-item {
    grid-template-columns: 1fr;
  }

  .top-bar {
    flex-direction: column;
  }
}
</style>
