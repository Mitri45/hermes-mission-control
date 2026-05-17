export interface MissionControlHealth {
  status: string
  plugin: string
  version: string
}

export interface MissionControlSection {
  id: string
  label: string
  status: string
}

export interface MissionControlSummary {
  plugin: string
  version: string
  status: string
  sections: MissionControlSection[]
}

declare global {
  interface Window {
    __HERMES_SESSION_TOKEN__?: string
    __HERMES_BASE_PATH__?: string
    __HERMES_PLUGIN_SDK__?: any
    __HERMES_PLUGINS__?: {
      register: (name: string, component: unknown) => void
      registerSlot?: (pluginName: string, slotName: string, component: unknown) => void
    }
  }
}
