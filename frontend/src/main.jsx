import React from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, Bot, Camera, Cpu, Gamepad2, Gauge, HelpCircle, MessageCircle, PauseCircle, Radar, RefreshCw, ShieldAlert, SlidersHorizontal, Sparkles, Wifi, Zap } from 'lucide-react'
import './styles.css'

const DEFAULT_DEVICE = import.meta.env.VITE_DEVICE_ID || 'VB-CAM-E9BFB4'
const DEFAULT_API = import.meta.env.VITE_API_BASE || `${window.location.protocol}//${window.location.hostname}:8000`
const APP_VERSION = 'v1.2.0 local LAN compose'
const DRIVE_INTERVAL_MS = 850
const DRIVE_TTL_MS = 2000

const FALLBACK_DETECTORS = [
  { id: 'yolo11n.onnx', label: 'ONNX — YOLO11n realtime', recommended_imgsz: 320, speed: 'realtime' },
  { id: 'yolo11n.onnx', label: 'ONNX — YOLO11n cân bằng', recommended_imgsz: 320, speed: 'balanced' },
  { id: 'yolov8n.onnx', label: 'ONNX — YOLOv8n fallback', recommended_imgsz: 416, speed: 'fallback' },
  { id: 'torchvision:ssdlite320_mobilenet_v3_large', label: 'SSD MobileNetV3 320 — không YOLO', recommended_imgsz: 320, speed: 'fast' },
]


const FALLBACK_VLMS = [
  { id: 'HuggingFaceTB/SmolVLM2-500M-Video-Instruct', label: 'SmolVLM2 500M — nhẹ nhất' },
  { id: 'HuggingFaceTB/SmolVLM-500M-Instruct', label: 'SmolVLM 500M — ổn định' },
]


const SUGGESTED_QUESTIONS = [
  'Trong khung hình có những vật gì?',
  'Có vật cản phía trước không?',
  'Robot nên đi tiếp hay dừng?',
  'Vật nào gần camera nhất?',
  'Có người hoặc xe trong ảnh không?',
  'Nếu đi thẳng có nguy hiểm không?'
]



const detectorOptionKey = (m) => `${m.id}||${m.recommended_imgsz || 320}||${m.speed || m.family || m.label || ''}`
const findDetectorByKey = (options, key) => options.find(m => detectorOptionKey(m) === key) || options[0]

// Hardware wiring note: this robot currently turns opposite on left/right.
// Keep UI logical: pressing “Trái/A” should make the robot turn left physically.
const LOGICAL_TO_HARDWARE_DRIVE = { left: 'right', right: 'left' }
const HARDWARE_TO_LOGICAL_DRIVE = { right: 'left', left: 'right' }
const toHardwareDrive = (cmd) => LOGICAL_TO_HARDWARE_DRIVE[cmd] || cmd
const toLogicalDrive = (cmd) => HARDWARE_TO_LOGICAL_DRIVE[cmd] || cmd

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms))
const seq32 = () => {
  const max = 2147483647
  const n = Date.now() % max
  return n > 0 ? n : 1
}
const fmtTime = () => new Date().toLocaleTimeString()
const isNearBottom = (el, px = 120) => !el || (el.scrollHeight - el.scrollTop - el.clientHeight < px)

function shortJson(value) {
  if (!value) return ''
  if (value.status && value.detail) return `${value.status}: ${value.detail}`
  if (value.detail?.error) return `${value.detail.error}: ${value.detail.message || ''}`
  if (value.error) return value.error
  if (value.robot_ack?.detail) return value.robot_ack.detail
  return ''
}

function summarizeAi(data) {
  const detectionBlock = data?.detections?.detections ? data.detections : data
  const dets = detectionBlock?.detections || []
  const detectError = detectionBlock?.error || data?.error
  const scene = data?.scene || {}
  const safety = data?.safety || {}
  const sceneError = scene?.error || ''
  const vlmDets = Array.isArray(scene?.detections) ? scene.detections : []

  if (detectError) {
    if (String(detectError).includes('ultralytics')) {
      return 'Mình chưa chạy được YOLO vì backend thiếu ultralytics. Hãy cài backend/requirements-ai.txt rồi restart backend.'
    }
    return `YOLO đang lỗi: ${detectError}`
  }

  const lines = []
  if (Array.isArray(dets) && dets.length) {
    lines.push('Detector realtime thấy các vật thể sau:')
    dets.slice(0, 8).forEach((d, idx) => {
      const label = d.label || d.name || d.class_name || 'object'
      const conf = Math.round((d.confidence || d.conf || 0) * 100)
      lines.push(`${idx + 1}. ${label} — độ tin cậy khoảng ${conf}%`)
    })
  } else {
    lines.push('Detector realtime chưa thấy vật thể rõ ràng trong frame này. Thử tăng ánh sáng, đưa vật thể gần hơn, hoặc chọn model mạnh hơn ở phần AI model.')
  }

  if (vlmDets.length) {
    lines.push('VLM cũng trả về bbox/nhãn:')
    vlmDets.slice(0, 8).forEach((d, idx) => lines.push(`${idx + 1}. ${d.label || 'object'} — nguồn ${d.source || 'vlm'}`))
  }

  const latency = detectionBlock?.inference_ms || data?.inference_ms
  if (latency) lines.push(`Detector xử lý frame này mất khoảng ${latency} ms.`)

  if (sceneError) {
    if (String(sceneError).includes('AI_ENABLE_VLM=0')) {
      lines.push('VLM đang tắt ở backend, nên mình mới chỉ phân tích bằng detector realtime.')
    } else if (String(sceneError).includes('transformers') || String(sceneError).includes('AutoModel')) {
      lines.push('VLM chưa load được vì thư viện transformers/model trong backend chưa đúng. Cần nâng dependencies rồi restart backend.')
    } else {
      lines.push(`VLM đang lỗi: ${sceneError}`)
    }
  } else {
    let sceneText = scene?.answer_vi || scene?.description_vi || scene?.description || scene?.caption_vi || scene?.caption || scene?.raw || ''
    if (sceneText && sceneText.length > 800) sceneText = sceneText.slice(-800)
    if (sceneText) lines.push(`VLM trả lời: ${sceneText}`)
  }

  const action = safety?.safe_action || scene?.suggested_action || scene?.action || ''
  if (action) lines.push(`Gợi ý an toàn: ${action}`)
  return lines.join('\n')
}

function StatChip({label, value}) {
  return <span className="statChip"><b>{label}</b>{value ?? '-'}</span>
}

function App() {
  const [apiBase, setApiBase] = React.useState(localStorage.getItem('apiBase') || DEFAULT_API)
  const [deviceId, setDeviceId] = React.useState(localStorage.getItem('deviceId') || DEFAULT_DEVICE)
  const [robot, setRobot] = React.useState(null)
  const [health, setHealth] = React.useState(null)
  const [aiStatus, setAiStatus] = React.useState(null)
  const [videoMode, setVideoMode] = React.useState('raw')
  const [videoOn, setVideoOn] = React.useState(false)
  const [servoAngle, setServoAngle] = React.useState(90)
  const [logs, setLogs] = React.useState([])
  const [aiMessages, setAiMessages] = React.useState([
    { role: 'assistant', time: fmtTime(), text: 'Mình là AI của VisionBot. Bấm Detect để benchmark detector/bbox realtime. Bấm VLM hoặc gõ câu hỏi để model nhìn frame hiện tại, nhận dạng vật thể và trả lời như chat. Lần đầu tải model sẽ lâu một chút.' }
  ])
  const [chatInput, setChatInput] = React.useState('')
  const [activeDrive, setActiveDrive] = React.useState(null)
  const [aiBusy, setAiBusy] = React.useState(false)
  const [aiUnread, setAiUnread] = React.useState(false)
  const [logUnread, setLogUnread] = React.useState(false)
  const [modelForm, setModelForm] = React.useState({
    detector_key: 'yolo11n.onnx||320||realtime',
    yolo_model: 'yolo11n.onnx', yolo_imgsz: 320, conf_threshold: 0.25, detect_interval_s: 0.2,
    enable_vlm: true, vlm_model: 'HuggingFaceTB/SmolVLM-500M-Instruct'
  })

  const activeDriveRef = React.useRef(null)
  const driveLoopRunningRef = React.useRef(false)
  const pressedKeys = React.useRef(new Set())
  const chatBoxRef = React.useRef(null)
  const logListRef = React.useRef(null)
  const aiStickRef = React.useRef(true)
  const logStickRef = React.useRef(true)
  const modelDirtyRef = React.useRef(false)
  const firstModelSyncRef = React.useRef(false)

  React.useEffect(() => {
    localStorage.setItem('apiBase', apiBase)
    localStorage.setItem('deviceId', deviceId)
  }, [apiBase, deviceId])

  React.useLayoutEffect(() => {
    const el = chatBoxRef.current
    if (!el) return
    if (aiStickRef.current) {
      el.scrollTop = el.scrollHeight
      setAiUnread(false)
    } else {
      setAiUnread(true)
    }
  }, [aiMessages.length])

  React.useLayoutEffect(() => {
    const el = logListRef.current
    if (!el) return
    if (logStickRef.current) {
      el.scrollTop = el.scrollHeight
      setLogUnread(false)
    } else {
      setLogUnread(true)
    }
  }, [logs.length])

  const scrollChatBottom = () => {
    const el = chatBoxRef.current
    if (el) el.scrollTop = el.scrollHeight
    aiStickRef.current = true
    setAiUnread(false)
  }
  const scrollLogBottom = () => {
    const el = logListRef.current
    if (el) el.scrollTop = el.scrollHeight
    logStickRef.current = true
    setLogUnread(false)
  }

  const pushLog = React.useCallback((type, message, data) => {
    logStickRef.current = isNearBottom(logListRef.current)
    setLogs(prev => [...prev, { time: fmtTime(), type, message, data }].slice(-160))
  }, [])

  const pushAi = React.useCallback((role, text, data) => {
    aiStickRef.current = role === 'user' || isNearBottom(chatBoxRef.current)
    setAiMessages(prev => [...prev, { role, time: fmtTime(), text, data }].slice(-80))
  }, [])

  const applyAckToRobot = React.useCallback((ack) => {
    if (!ack) return
    setRobot(prev => prev ? ({
      ...prev,
      state: {
        ...(prev.state || {}),
        motor_state: ack.motor_state ? toLogicalDrive(ack.motor_state) : prev.state?.motor_state,
        servo_angle: ack.servo_angle ?? prev.state?.servo_angle,
        mode: ack.mode ?? prev.state?.mode,
        last_cmd_seq: ack.seq ?? prev.state?.last_cmd_seq,
        last_cmd_ack_status: ack.status ?? prev.state?.last_cmd_ack_status,
        last_cmd_ack_detail: ack.detail ?? prev.state?.last_cmd_ack_detail,
      },
      motor_state: ack.motor_state ? toLogicalDrive(ack.motor_state) : prev.motor_state,
      servo_angle: ack.servo_angle ?? prev.servo_angle,
      last_cmd_ack: ack,
    }) : prev)
  }, [])

  const api = React.useCallback(async (path, options = {}) => {
    const res = await fetch(`${apiBase}${path}`, options)
    const data = await res.json().catch(() => ({ detail: 'non_json_response' }))
    if (!res.ok) {
      pushLog('err', `${res.status} ${path}`, data)
      throw data
    }
    return data
  }, [apiBase, pushLog])

  const syncModelForm = React.useCallback((status) => {
    const yolo = status?.ai?.yolo || status?.yolo
    const vlm = status?.ai?.vlm || status?.vlm
    if (!yolo && !vlm) return
    const options = status?.presets?.detector_presets || FALLBACK_DETECTORS
    const matched = options.find(m => m.id === yolo?.model && Number(m.recommended_imgsz || 0) === Number(yolo?.imgsz || 0)) || options.find(m => m.id === yolo?.model)
    setModelForm(prev => ({
      ...prev,
      detector_key: matched ? detectorOptionKey(matched) : prev.detector_key,
      yolo_model: yolo?.model || prev.yolo_model,
      yolo_imgsz: yolo?.imgsz || prev.yolo_imgsz,
      conf_threshold: yolo?.conf_threshold ?? prev.conf_threshold,
      detect_interval_s: yolo?.detect_interval_s ?? prev.detect_interval_s,
      enable_vlm: vlm?.enabled ?? prev.enable_vlm,
      vlm_model: vlm?.model || prev.vlm_model,
    }))
  }, [])

  const refresh = React.useCallback(async () => {
    try {
      const h = await api('/api/health')
      setHealth(h)
      const r = await api(`/api/robots/${deviceId}`)
      setRobot(r)
      setServoAngle(r?.state?.servo_angle ?? r?.servo_angle ?? 90)
      try {
        const s = await api(`/api/robots/${deviceId}/ai/status`)
        setAiStatus(s)
        // Do not overwrite the user's dropdown while they are choosing a model.
        // The old UI re-synced from backend every poll, so the select jumped back
        // to the currently-running model before the user could press “Áp dụng”.
        if (!firstModelSyncRef.current || !modelDirtyRef.current) {
          syncModelForm(s)
          firstModelSyncRef.current = true
        }
      } catch (_) {}
    } catch (_) {}
  }, [api, deviceId, syncModelForm])

  React.useEffect(() => {
    refresh()
    const t = setInterval(refresh, activeDrive ? 500 : 1200)
    return () => clearInterval(t)
  }, [refresh, activeDrive])

  const startCamera = async (mode = videoMode) => {
    await api(`/api/robots/${deviceId}/camera/start`, { method: 'POST' })
    setVideoMode(mode)
    setVideoOn(true)
    pushLog('ok', `video ${mode} started`)
    refresh()
  }

  const stopCamera = async () => {
    setVideoOn(false)
    try {
      const data = await api(`/api/robots/${deviceId}/camera/stop`, { method: 'POST' })
      pushLog('ok', 'stream video stopped', data)
    } catch (err) {
      pushLog('err', 'stop stream failed', err)
    }
    refresh()
  }

  const videoUrl = videoMode === 'ai'
    ? `${apiBase}/api/robots/${deviceId}/ai/video.mjpg?t=${videoMode}-${videoOn}`
    : `${apiBase}/api/robots/${deviceId}/video.mjpg?t=${videoMode}-${videoOn}`

  const commandDrive = React.useCallback(async (logicalCmd) => {
    const hardwareCmd = toHardwareDrive(logicalCmd)
    const payload = { seq: seq32(), cmd: hardwareCmd, ttl_ms: DRIVE_TTL_MS, mode: 'manual' }
    if (logicalCmd !== 'stop') {
      setRobot(prev => prev ? ({ ...prev, state: { ...(prev.state || {}), motor_state: logicalCmd } }) : prev)
    }
    const data = await api(`/api/robots/${deviceId}/control/drive`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    })
    applyAckToRobot(data.robot_ack)
    pushLog('ack', hardwareCmd === logicalCmd ? `drive ${logicalCmd}` : `drive ${logicalCmd} → gửi ${hardwareCmd} để sửa đảo trái/phải`, data.robot_ack || data)
    return data
  }, [api, deviceId, pushLog, applyAckToRobot])

  const runDriveLoop = React.useCallback(async (cmd) => {
    if (driveLoopRunningRef.current) return
    driveLoopRunningRef.current = true
    try {
      while (activeDriveRef.current === cmd) {
        await commandDrive(cmd).catch(() => {})
        await sleep(DRIVE_INTERVAL_MS)
      }
    } finally {
      driveLoopRunningRef.current = false
    }
  }, [commandDrive])

  const beginDrive = React.useCallback((cmd) => {
    if (activeDriveRef.current === cmd) return
    activeDriveRef.current = cmd
    setActiveDrive(cmd)
    setRobot(prev => prev ? ({ ...prev, state: { ...(prev.state || {}), motor_state: cmd } }) : prev)
    runDriveLoop(cmd)
  }, [runDriveLoop])

  const endDrive = React.useCallback(() => {
    if (!activeDriveRef.current) return
    activeDriveRef.current = null
    setActiveDrive(null)
    setRobot(prev => prev ? ({ ...prev, state: { ...(prev.state || {}), motor_state: 'stop' } }) : prev)
    commandDrive('stop').catch(() => {})
  }, [commandDrive])

  React.useEffect(() => {
    const keyToCmd = (key) => ({ w: 'forward', W: 'forward', ArrowUp: 'forward', s: 'backward', S: 'backward', ArrowDown: 'backward', a: 'left', A: 'left', ArrowLeft: 'left', d: 'right', D: 'right', ArrowRight: 'right' }[key])
    const isTyping = (target) => ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName)
    const down = (e) => {
      if (isTyping(e.target)) return
      const cmd = keyToCmd(e.key)
      if (!cmd || pressedKeys.current.has(e.key)) return
      e.preventDefault()
      pressedKeys.current.add(e.key)
      beginDrive(cmd)
    }
    const up = (e) => {
      if (isTyping(e.target)) return
      const cmd = keyToCmd(e.key)
      if (!cmd) return
      e.preventDefault()
      pressedKeys.current.delete(e.key)
      if (pressedKeys.current.size === 0) endDrive()
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', endDrive)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', endDrive)
    }
  }, [beginDrive, endDrive])

  const setModeManual = async () => {
    const data = await api(`/api/robots/${deviceId}/control/mode/manual`, { method: 'POST' })
    applyAckToRobot(data.robot_ack)
    pushLog('ack', 'mode manual', data.robot_ack || data)
    refresh()
  }

  const estop = async () => {
    endDrive()
    const data = await api(`/api/robots/${deviceId}/control/stop`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ seq: seq32(), reason: 'frontend_emergency_stop' })
    })
    applyAckToRobot(data.robot_ack)
    pushLog('ack', 'EMERGENCY STOP', data.robot_ack || data)
    refresh()
  }

  const servo = async (angle) => {
    setServoAngle(angle)
    const data = await api(`/api/robots/${deviceId}/control/servo`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ seq: seq32(), angle })
    })
    applyAckToRobot(data.robot_ack)
    pushLog('ack', `servo ${angle}`, data.robot_ack || data)
  }

  const applyAiConfig = async (patch = null) => {
    const payload = patch || {
      yolo_model: modelForm.yolo_model,
      yolo_imgsz: Number(modelForm.yolo_imgsz),
      conf_threshold: Number(modelForm.conf_threshold),
      detect_interval_s: Number(modelForm.detect_interval_s),
      enable_vlm: Boolean(modelForm.enable_vlm),
      vlm_model: modelForm.vlm_model,
    }
    try {
      const data = await api('/api/ai/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      })
      setAiStatus(prev => ({ ...(prev || {}), ai: data.ai, presets: data.presets }))
      modelDirtyRef.current = false
      syncModelForm(data)
      pushAi('assistant', `Đã đổi cấu hình AI. Detector: ${data.ai?.yolo?.model}, imgsz ${data.ai?.yolo?.imgsz}, conf ${data.ai?.yolo?.conf_threshold}. VLM: ${data.ai?.vlm?.enabled ? 'bật' : 'tắt'} (${data.ai?.vlm?.model || modelForm.vlm_model}).`, data)
      pushLog('ok', 'AI config updated', data)
    } catch (err) {
      pushAi('assistant', 'Mình chưa đổi được cấu hình AI. Mở JSON kỹ thuật để xem lỗi backend.', err)
    }
  }



  const preloadSelectedModel = async () => {
    await applyAiConfig()
    setAiBusy(true)
    pushAi('user', `Tải model đang chọn: ${modelForm.yolo_model}${modelForm.enable_vlm ? ' + VLM ' + modelForm.vlm_model : ''}`)
    try {
      const data = await api(`/api/ai/preload?load_detector=true&load_vlm=${modelForm.enable_vlm ? 'true' : 'false'}`, { method: 'POST' })
      setAiStatus(prev => ({ ...(prev || {}), ai: data.ai, presets: data.presets }))
      pushAi('assistant', 'Mình đã tải/khởi động model đang chọn xong. Nếu model lớn, lần đầu có thể mất lâu; lần sau dùng cache local.', data)
      pushLog('ok', 'AI model preloaded', data)
    } catch (err) {
      pushAi('assistant', 'Mình chưa preload được model. Mở JSON kỹ thuật để xem lỗi.', err)
    } finally {
      setAiBusy(false)
    }
  }

  const applyProfile = (name) => {
    const profiles = {
      realtime: { detector_key: 'yolo11n.onnx||320||realtime', yolo_model: 'yolo11n.onnx', yolo_imgsz: 320, conf_threshold: 0.25, detect_interval_s: 0.20 },
      balanced: { detector_key: 'yolo11n.onnx||320||balanced', yolo_model: 'yolo11n.onnx', yolo_imgsz: 320, conf_threshold: 0.25, detect_interval_s: 0.30 },
      fallback: { detector_key: 'yolov8n.onnx||416||fallback', yolo_model: 'yolov8n.onnx', yolo_imgsz: 416, conf_threshold: 0.25, detect_interval_s: 0.35 },
      mobilenet: { detector_key: 'torchvision:ssdlite320_mobilenet_v3_large||320||fast', yolo_model: 'torchvision:ssdlite320_mobilenet_v3_large', yolo_imgsz: 320, conf_threshold: 0.30, detect_interval_s: 0.50 },
      fasterrcnn: { detector_key: 'torchvision:fasterrcnn_mobilenet_v3_large_320_fpn||320||fasterrcnn', yolo_model: 'torchvision:fasterrcnn_mobilenet_v3_large_320_fpn', yolo_imgsz: 320, conf_threshold: 0.35, detect_interval_s: 1.00 },
      strong: { detector_key: 'yolo11s.onnx||512||strong', yolo_model: 'yolo11s.onnx', yolo_imgsz: 512, conf_threshold: 0.25, detect_interval_s: 0.50 },
    }
    const p = profiles[name]
    if (!p) return
    setModelForm(prev => ({ ...prev, ...p }))
    applyAiConfig(p)
  }

  const runAiDetect = async () => {
    pushAi('user', 'Nhìn frame hiện tại và nhận diện vật thể.')
    setAiBusy(true)
    try {
      const data = await api(`/api/robots/${deviceId}/ai/detect?force=true`)
      pushAi('assistant', summarizeAi(data), data)
      setAiStatus(prev => prev ? ({ ...prev, ai: { ...prev.ai, yolo: { ...(prev.ai?.yolo || {}), last_inference_ms: data.inference_ms, last_objects: data.detections_count, model: data.model } } }) : prev)
      pushLog('ai', `Detect: ${data.detections_count ?? (data.detections || []).length} objects`, data)
    } catch (err) {
      pushAi('assistant', 'Mình chưa detect được. Thường là model chưa tải xong, thiếu thư viện, hoặc chưa có frame camera.', err)
    } finally {
      setAiBusy(false)
    }
  }

  const runAiAnalyze = async () => {
    pushAi('user', 'Dùng VLM nhìn frame hiện tại: nhận dạng vật thể, vật cản, nên đi hay dừng?')
    setAiBusy(true)
    try {
      const data = await api(`/api/robots/${deviceId}/ai/analyze`)
      pushAi('assistant', summarizeAi(data), data)
      pushLog('ai', 'VLM scene analysis', data)
    } catch (err) {
      pushAi('assistant', 'Mình chưa phân tích cảnh được. Nếu lỗi AutoModel/transformers thì cần nâng transformers rồi restart backend.', err)
    } finally {
      setAiBusy(false)
    }
  }

  const askAiQuestion = async (q) => {
    const question = String(q || '').trim()
    if (!question || aiBusy) return
    pushAi('user', question)
    setAiBusy(true)
    try {
      const data = await api(`/api/robots/${deviceId}/ai/ask`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question })
      })
      pushAi('assistant', summarizeAi(data), data)
      pushLog('ai', 'AI chat question', data)
    } catch (err) {
      pushAi('assistant', 'Mình chưa trả lời được câu hỏi này. Nếu VLM đang tắt, model chưa tải xong, hoặc model này không tương thích loader hiện tại thì xem JSON kỹ thuật rồi đổi sang SmolVLM/Qwen khác.', err)
    } finally {
      setAiBusy(false)
    }
  }

  const submitAiChat = async (e) => {
    e.preventDefault()
    const q = chatInput.trim()
    if (!q) return
    setChatInput('')
    await askAiQuestion(q)
  }

  const pill = (ok, text) => <span className={`pill ${ok ? 'ok' : 'bad'}`}>{text}</span>
  const cam = robot?.camera_session || aiStatus?.camera_session || {}
  const yolo = aiStatus?.ai?.yolo || health?.ai?.status?.yolo || {}
  const vlm = aiStatus?.ai?.vlm || health?.ai?.status?.vlm || {}
  const detectorOptions = aiStatus?.presets?.detector_presets || FALLBACK_DETECTORS
  const vlmOptions = aiStatus?.presets?.vlm_presets || FALLBACK_VLMS
  const detMetric = yolo.benchmark || yolo.model_metric || null
  const vlmMetric = vlm.benchmark || null
  const reportedMotor = robot?.state?.motor_state || robot?.motor_state || '-'
  const motorShown = activeDrive ? `${activeDrive} (lệnh đang giữ)` : reportedMotor
  const lastAck = robot?.state?.last_cmd_ack_detail || robot?.last_cmd_ack?.detail || '-'

  return <div className="app">
    <header className="hero">
      <div>
        <div className="eyebrow"><Bot size={18}/> VisionBot Control Center <span>{APP_VERSION}</span></div>
        <h1>Robot AI/IoT Dashboard</h1>
        <p>Frontend React gọi Backend FastAPI. Backend publish MQTT xuống ESP32-CAM. AI rút gọn ổn định: YOLO/SSD realtime + VLM hỏi frame. Bản LAN chạy bằng Docker Compose.</p>
      </div>
      <div className="statusBox">
        {pill(!!health?.mqtt_connected, health?.mqtt_connected ? 'MQTT backend OK' : 'MQTT backend lỗi')}
        {pill(!!robot?.online, robot?.online ? 'Robot online' : 'Robot offline')}
        {pill(!!robot?.mqtt_connected, robot?.mqtt_connected ? 'Robot MQTT OK' : 'Robot MQTT lỗi')}
      </div>
    </header>

    <section className="config card">
      <label>Backend API<input value={apiBase} onChange={e => setApiBase(e.target.value)} /></label>
      <label>Device ID<input value={deviceId} onChange={e => setDeviceId(e.target.value)} /></label>
      <button className="primary" onClick={refresh} title="Gọi /api/health và /api/robots để cập nhật trạng thái"><RefreshCw size={18}/> Làm mới</button>
      <button onClick={setModeManual} title="Đưa robot về manual, thoát estop để được phép điều khiển"><Gamepad2 size={18}/> Manual mode</button>
      <button className="danger" onClick={estop} title="Dừng khẩn cấp, robot vào estop. Muốn chạy lại phải bấm Manual mode"><ShieldAlert size={18}/> Dừng khẩn cấp</button>
    </section>

    <section className="helpStrip card">
      <div><HelpCircle size={18}/><b>Ý nghĩa nút:</b></div>
      <span><b>Video raw</b> xem camera gốc</span>
      <span><b>AI overlay</b> camera có bbox detector</span>
      <span><b>Detect</b> nhận diện một frame</span>
      <span><b>VLM</b> hỏi AI nhận dạng/caption/grounding theo frame</span>
      <span><b>Tắt stream</b> ngắt receiver camera ở backend</span>
      <span><b>W/A/S/D</b> giữ để chạy, thả để dừng</span>
    </section>

    <main className="grid">
      <section className="leftStack">
      <section className="card videoCard">
        <div className="cardTitle"><Camera/> Camera</div>
        <div className="toolbar">
          <button className={videoMode === 'raw' && videoOn ? 'selected' : ''} onClick={() => startCamera('raw')}>Video raw</button>
          <button className={videoMode === 'ai' && videoOn ? 'selected' : ''} onClick={() => startCamera('ai')}><Radar size={17}/> AI overlay</button>
          <button onClick={runAiDetect}><Cpu size={17}/> Detect</button>
          <button onClick={runAiAnalyze}><Sparkles size={17}/> VLM</button>
          <button className="softDanger" onClick={stopCamera}><PauseCircle size={17}/> Tắt stream</button>
        </div>
        <div className="statsRow">
          <StatChip label="Stream FPS" value={cam.stream_fps ?? '-'} />
          <StatChip label="Frame" value={cam.latest_frame_kb ? `${cam.latest_frame_kb} KB` : '-'} />
          <StatChip label="Detector" value={yolo.model || '-'} />
          <StatChip label="Backend" value={yolo.backend || '-'} />
          <StatChip label="Infer" value={yolo.last_inference_ms ? `${yolo.last_inference_ms} ms` : '-'} />
          <StatChip label="Avg" value={detMetric?.avg_ms ? `${detMetric.avg_ms} ms` : '-'} />
          <StatChip label="AI FPS" value={detMetric?.approx_fps || yolo.approx_detect_fps || '-'} />
          <StatChip label="Objects" value={yolo.last_objects ?? '-'} />
        </div>
        <div className="modelPanel">
          <div className="modelHeader"><SlidersHorizontal size={17}/><b>AI model runtime</b><span>Danh sách rút gọn để giữ stream ổn định. Chọn model → Áp dụng → Tải model → Detect.</span></div>
          <div className="modelGrid">
            <label>Detector
              <select value={modelForm.detector_key} onChange={e => {
                const selected = findDetectorByKey(detectorOptions, e.target.value)
                modelDirtyRef.current = true
                setModelForm(v => ({ ...v, detector_key: detectorOptionKey(selected), yolo_model: selected.id, yolo_imgsz: selected.recommended_imgsz || v.yolo_imgsz }))
              }}>
                {detectorOptions.map((m, idx) => <option key={`${detectorOptionKey(m)}-${idx}`} value={detectorOptionKey(m)}>{m.label || m.id}</option>)}
              </select>
            </label>
            <label>imgsz
              <select value={modelForm.yolo_imgsz} onChange={e => { modelDirtyRef.current = true; setModelForm(v => ({ ...v, yolo_imgsz: Number(e.target.value) })) }}>
                {[320, 416, 512, 640, 768].map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>
            <label>conf
              <input type="number" min="0.05" max="0.95" step="0.05" value={modelForm.conf_threshold} onChange={e => { modelDirtyRef.current = true; setModelForm(v => ({ ...v, conf_threshold: Number(e.target.value) })) }}/>
            </label>
            <label>interval(s)
              <input type="number" min="0.05" max="5" step="0.05" value={modelForm.detect_interval_s} onChange={e => { modelDirtyRef.current = true; setModelForm(v => ({ ...v, detect_interval_s: Number(e.target.value) })) }}/>
            </label>
            <button onClick={() => applyAiConfig()}><SlidersHorizontal size={17}/> Áp dụng</button>
            <button type="button" onClick={preloadSelectedModel}><Cpu size={17}/> Tải model</button>
          </div>
          <div className="metricMini">
            <span><b>Detector latency:</b> last {detMetric?.last_ms ?? yolo.last_inference_ms ?? '-'} ms · avg {detMetric?.avg_ms ?? yolo.avg_inference_ms ?? '-'} ms · FPS {detMetric?.approx_fps ?? yolo.approx_detect_fps ?? '-'}</span>
            <span><b>VLM latency:</b> last {vlmMetric?.last_ms ?? vlm.last_inference_ms ?? '-'} ms · avg {vlmMetric?.avg_ms ?? vlm.avg_inference_ms ?? '-'} ms · FPS {vlmMetric?.approx_fps ?? '-'}</span>
          </div>
          <div className="quickProfiles">
            <button onClick={() => applyProfile('realtime')}><Zap size={16}/> YOLO realtime</button>
            <button onClick={() => applyProfile('balanced')}>YOLO cân bằng</button>
            <button onClick={() => applyProfile('mobilenet')}>SSD MobileNet</button>
            <button onClick={() => applyProfile('fasterrcnn')}>Faster R-CNN</button>
            <button onClick={() => applyProfile('strong')}>YOLO mạnh hơn</button>
          </div>
          <div className="vlmGrid">
            <label className="toggleLine">
              <input type="checkbox" checked={modelForm.enable_vlm} onChange={e => { modelDirtyRef.current = true; setModelForm(v => ({ ...v, enable_vlm: e.target.checked })) }}/>
              Bật VLM hỏi-đáp theo frame
            </label>
            <label>VLM model
              <select value={modelForm.vlm_model} onChange={e => { modelDirtyRef.current = true; setModelForm(v => ({ ...v, vlm_model: e.target.value })) }}>
                {vlmOptions.map(m => <option key={m.id} value={m.id}>{m.label || m.id}</option>)}
              </select>
            </label>
            <button onClick={() => applyAiConfig({ enable_vlm: true, vlm_model: modelForm.vlm_model })}><Sparkles size={16}/> Bật VLM</button>
          </div>
        </div>
        <div className="videoFrame">
          {videoOn ? <img src={videoUrl} alt="VisionBot stream" /> : <div className="placeholder">Bấm Video raw hoặc AI overlay để bắt đầu stream</div>}
        </div>
        <p className="hint">Camera FPS và detector FPS là hai thứ khác nhau. Nếu AI overlay lag, chuyển về Video raw khi lái robot; dùng Detect khi cần nhận dạng.</p>
      </section>

      <section className="card logs">
        <div className="cardTitle"><Activity/> cmd_ack / logs</div>
        <div className="logList" ref={logListRef} onScroll={() => { logStickRef.current = isNearBottom(logListRef.current); if (logStickRef.current) setLogUnread(false) }}>
          {logs.map((l, i) => <div className={`log ${l.type}`} key={i}>
            <div className="logHead"><b>{l.time}</b> <span>{l.message}</span> <em>{shortJson(l.data)}</em></div>
            {l.data && <details><summary>Chi tiet JSON</summary><pre>{JSON.stringify(l.data, null, 2)}</pre></details>}
          </div>)}
        </div>
        {logUnread && <button className="jumpBtn" onClick={scrollLogBottom}>Log moi ↓</button>}
      </section>
      </section>

      <section className="sideStack">
      <section className="card controlCard">
        <div className="cardTitle"><Gamepad2/> Điều khiển giữ-nút</div>
        <p className="hint">Giữ W/A/S/D hoặc nút bên dưới để chạy. Thả tay sẽ gửi stop. Đã sửa đảo trái/phải theo wiring hiện tại. Mất mạng thì TTL vẫn tự dừng.</p>
        <div className="driveStatus">Lệnh hiện tại: <b>{motorShown}</b></div>
        <div className="pad" onContextMenu={(e) => e.preventDefault()}>
          <button className={activeDrive === 'forward' ? 'active' : ''} onPointerDown={() => beginDrive('forward')} onPointerUp={endDrive} onPointerCancel={endDrive} onPointerLeave={endDrive}>Tiến<br/><kbd>W</kbd></button>
          <div className="padRow">
            <button className={activeDrive === 'left' ? 'active' : ''} onPointerDown={() => beginDrive('left')} onPointerUp={endDrive} onPointerCancel={endDrive} onPointerLeave={endDrive}>Trái<br/><kbd>A</kbd></button>
            <button className={activeDrive === 'right' ? 'active' : ''} onPointerDown={() => beginDrive('right')} onPointerUp={endDrive} onPointerCancel={endDrive} onPointerLeave={endDrive}>Phải<br/><kbd>D</kbd></button>
          </div>
          <button className={activeDrive === 'backward' ? 'active' : ''} onPointerDown={() => beginDrive('backward')} onPointerUp={endDrive} onPointerCancel={endDrive} onPointerLeave={endDrive}>Lùi<br/><kbd>S</kbd></button>
        </div>
        <div className="servo">
          <div className="cardTitle small"><Gauge/> Servo: {servoAngle}°</div>
          {[0,45,90,135,180].map(a => <button key={a} onClick={() => servo(a)} className={servoAngle === a ? 'selected' : ''}>{a}°</button>)}
        </div>
      </section>

      <section className="card facts">
        <div className="cardTitle"><Wifi/> Robot state</div>
        <dl>
          <dt>IP</dt><dd>{robot?.ip || '-'}</dd>
          <dt>Firmware</dt><dd>{robot?.firmware || '-'}</dd>
          <dt>Lệnh motor</dt><dd>{motorShown}</dd>
          <dt>ESP báo</dt><dd>{reportedMotor}</dd>
          <dt>Last ack</dt><dd>{lastAck}</dd>
          <dt>Servo</dt><dd>{robot?.state?.servo_angle ?? robot?.servo_angle ?? '-'}</dd>
          <dt>RSSI</dt><dd>{robot?.state?.wifi_rssi_dbm ?? '-'}</dd>
          <dt>Camera</dt><dd>{robot?.camera_ready ? 'ready' : '-'}</dd>
          <dt>VLM</dt><dd>{vlm.enabled ? (vlm.loaded ? 'loaded' : 'enabled') : 'off'}</dd>
        </dl>
      </section>

      <section className="card aiPanel">
        <div className="cardTitle"><MessageCircle/> AI chat / result</div>
        <div className="chatBox" ref={chatBoxRef} onScroll={() => { aiStickRef.current = isNearBottom(chatBoxRef.current); if (aiStickRef.current) setAiUnread(false) }}>
          {aiMessages.map((m, i) => <div key={i} className={`msg ${m.role}`}>
            <div className="msgMeta">{m.role === 'user' ? 'Bạn' : 'VisionBot AI'} · {m.time}</div>
            <div className="bubble">{m.text}</div>
            {m.data && <details><summary>Xem JSON kỹ thuật</summary><pre>{JSON.stringify(m.data, null, 2)}</pre></details>}
          </div>)}
          {aiBusy && <div className="msg assistant typingMsg">
            <div className="msgMeta">VisionBot AI · đang suy luận</div>
            <div className="bubble typingBubble"><span></span><span></span><span></span></div>
          </div>}
        </div>
        {aiUnread && <button className="jumpBtn" onClick={scrollChatBottom}>Tin AI mới ↓</button>}
        <div className="suggestionBar">
          {SUGGESTED_QUESTIONS.map(q => <button type="button" key={q} onClick={() => askAiQuestion(q)} disabled={aiBusy}>{q}</button>)}
        </div>
        <form className="chatInput" onSubmit={submitAiChat}>
          <input value={chatInput} onChange={e => setChatInput(e.target.value)} placeholder="Hỏi AI về khung hình hiện tại... ví dụ: phía trước có vật cản không?" />
          <button type="submit" disabled={aiBusy}><Sparkles size={16}/> {aiBusy ? 'Đang nghĩ...' : 'Gửi'}</button>
        </form>
      </section>

      </section>


    </main>
  </div>
}

createRoot(document.getElementById('root')).render(<App />)
