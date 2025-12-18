type JitsiEventHandler = (...args: unknown[]) => void

export interface JitsiExternalAPI {
  addEventListener: (event: string, handler: JitsiEventHandler) => void
  removeEventListener: (event: string, handler: JitsiEventHandler) => void
  executeCommand: (command: string, ...args: unknown[]) => void
  isAudioMuted: () => Promise<boolean>
  isVideoMuted: () => Promise<boolean>
  dispose: () => void
}

export interface StartJitsiParams {
  domain: string
  roomName: string
  parentNode: HTMLElement
  userInfo?: {
    displayName?: string
  }
  onReadyToClose?: () => void
  onConferenceLeft?: () => void
}

type JitsiExternalAPIConstructor = new (domain: string, options: Record<string, unknown>) => JitsiExternalAPI

declare global {
  interface Window {
    JitsiMeetExternalAPI?: JitsiExternalAPIConstructor
  }
}

const scriptPromises = new Map<string, Promise<void>>()

export async function startJitsiMeeting({
  domain,
  roomName,
  parentNode,
  userInfo,
  onConferenceLeft,
  onReadyToClose,
}: StartJitsiParams): Promise<JitsiExternalAPI> {
  const { apiDomain, scriptOrigin } = normalizeDomain(domain)

  await loadExternalApi(scriptOrigin)

  if (!window.JitsiMeetExternalAPI) {
    throw new Error('Jitsi IFrame API introuvable après chargement du script')
  }

  const api = new window.JitsiMeetExternalAPI(apiDomain, {
    roomName,
    parentNode,
    height: '100%',
    width: '100%',
    userInfo,
    configOverwrite: {
      prejoinPageEnabled: false,
      prejoinConfig: {
        enabled: false,
      },
      startAudioMuted: 0,
      startVideoMuted: 0,
      startWithAudioMuted: false,
      startWithVideoMuted: false,
      disableDeepLinking: true,
    },
  })

  api.addEventListener('videoConferenceJoined', async () => {
    try {
      const audioMuted = await api.isAudioMuted()
      if (audioMuted) {
        api.executeCommand('toggleAudio')
      }

      const videoMuted = await api.isVideoMuted()
      if (videoMuted) {
        api.executeCommand('toggleVideo')
      }
    } catch (error) {
      console.warn('Auto-unmute failed', error)
    }
  })

  if (onReadyToClose) {
    api.addEventListener('readyToClose', onReadyToClose)
  }

  if (onConferenceLeft) {
    api.addEventListener('videoConferenceLeft', onConferenceLeft)
  }

  return api
}

async function loadExternalApi(origin: string) {
  if (!scriptPromises.has(origin)) {
    const promise = new Promise<void>((resolve, reject) => {
      const script = document.createElement('script')
      script.src = `${origin.replace(/\/$/, '')}/external_api.js`
      script.async = true
      script.onload = () => resolve()
      script.onerror = () => reject(new Error(`Impossible de charger ${script.src}`))

      document.head.appendChild(script)
    })

    scriptPromises.set(origin, promise)
  }

  return scriptPromises.get(origin)!
}

function normalizeDomain(domain: string) {
  if (domain.startsWith('http')) {
    const url = new URL(domain)
    return {
      apiDomain: url.host,
      scriptOrigin: url.origin,
    }
  }

  return {
    apiDomain: domain,
    scriptOrigin: `https://${domain}`,
  }
}
