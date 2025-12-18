import ICAL from 'ical.js'

export interface Meeting {
  uid: string
  summary: string
  description: string
  start: Date
  end: Date
  location?: string
  conferenceUrl?: string
}

export interface AgendaSnapshot {
  events: Meeting[]
  current?: Meeting
  next?: Meeting
}

const URL_REGEX = /https?:\/\/\S+/i

export async function loadAgenda(icsUrl: string, now = new Date()): Promise<AgendaSnapshot> {
  const icsText = await fetchCalendar(icsUrl)
  const events = parseEvents(icsText)
  const { current, next } = pickCurrentAndNext(events, now)

  return { events, current, next }
}

async function fetchCalendar(url: string): Promise<string> {
  const response = await fetch(url, { cache: 'no-store' })

  if (!response.ok) {
    throw new Error(`Impossible de charger l'ICS (${response.status})`)
  }

  return response.text()
}

function parseEvents(icsText: string): Meeting[] {
  const jCalData = ICAL.parse(icsText)
  const vcalendar = new ICAL.Component(jCalData)

  registerTimezones(vcalendar)

  const vevents = vcalendar.getAllSubcomponents('vevent')
  const meetings: Meeting[] = []

  for (const component of vevents) {
    const event = new ICAL.Event(component)

    if (!event.startDate || !event.endDate) {
      continue
    }

    const start = event.startDate.toJSDate()
    const end = event.endDate.toJSDate()

    const conferenceProp = component.getFirstPropertyValue('x-conference') as string | undefined
    const rawDescription = event.description || ''
    const description = cleanDescription(rawDescription)
    const conferenceUrl = extractConferenceUrl(conferenceProp, rawDescription)

    meetings.push({
      uid: event.uid || `${start.getTime()}`,
      summary: event.summary || 'Réunion',
      description,
      start,
      end,
      location: event.location || undefined,
      conferenceUrl,
    })
  }

  return meetings.sort((a, b) => a.start.getTime() - b.start.getTime())
}

function registerTimezones(vcalendar: ICAL.Component) {
  const timezones = vcalendar.getAllSubcomponents('vtimezone')

  for (const component of timezones) {
    const tzid = component.getFirstPropertyValue('tzid') as string | undefined

    if (!tzid || ICAL.TimezoneService.has(tzid)) {
      continue
    }

    const timezone = new ICAL.Timezone({ component, tzid })

    if (timezone.tzid) {
      ICAL.TimezoneService.register(timezone, timezone.tzid)
    }
  }
}

function extractConferenceUrl(xConference?: string, description?: string): string | undefined {
  if (xConference) {
    const trimmed = xConference.trim()
    if (URL_REGEX.test(trimmed)) {
      return trimmed
    }
  }

  if (description) {
    const match = description.match(URL_REGEX)
    if (match) {
      return match[0].replace(/\)*$/, '')
    }
  }

  return undefined
}

function cleanDescription(description: string): string {
  if (!description) return ''

  // Supprime le bloc d'instructions encadré par des séquences ~.~ puis nettoie les résidus
  const withoutBlock = description.replace(/[~.\s]{3,}.*?[~.\s]{3,}/gs, ' ')
  const withoutNoise = withoutBlock.replace(/[~.\s]{3,}/g, ' ')
  return withoutNoise.replace(/\s+/g, ' ').trim()
}

function pickCurrentAndNext(events: Meeting[], now: Date) {
  let current: Meeting | undefined
  let next: Meeting | undefined

  for (const event of events) {
    if (now >= event.start && now < event.end) {
      current = event
    }

    if (!next && event.start > now) {
      next = event
    }

    if (current && next) {
      break
    }
  }

  return { current, next }
}
