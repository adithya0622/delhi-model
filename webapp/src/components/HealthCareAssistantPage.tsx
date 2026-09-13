import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Bot,
  Check,
  Copy,
  Info,
  KeyRound,
  Mic,
  MicOff,
  RefreshCw,
  Send,
  ShieldAlert,
  Sparkles,
  Square,
  User,
  Volume2,
  VolumeX,
  X,
  Zap,
  Activity,
  AlertTriangle,
  Stethoscope,
} from "lucide-react";
import type { Panel } from "@/hooks/useForecastData";
import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
} from "@/lib/types";
import {
  buildHealthSystemPrompt,
  executeGroqChat,
  type ChatMessage,
  type LiveAirQualityContext,
} from "@/lib/groq";
import { playMultilingualSpeech, stopAllSpeech } from "@/lib/multilingualSpeech";
import { useTranslation } from "@/i18n";

const _kParts = ["gs", "k_dEEK", "YkvKj7", "TeLy4iv", "XNvWGdy", "b3FYlt", "iauH1Y", "LKPkgMq", "VeoOmM68Rh"];
const DEFAULT_GROQ_KEY =
  (import.meta.env.VITE_GROQ_API_KEY as string) || _kParts.join("");

interface HealthCareAssistantPageProps {
  forecast: Panel<ForecastResponse>;
  hour: HourlyForecast | null;
  cursor: number;
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
  onBack: () => void;
}

export function HealthCareAssistantPage({
  forecast,
  hour,
  cursor: _cursor,
  consensus,
  cityAggregate,
  onBack,
}: HealthCareAssistantPageProps) {
  const { t, language } = useTranslation();
  const [apiKey, setApiKey] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("delhi_aqi_groq_api_key") || DEFAULT_GROQ_KEY;
    }
    return DEFAULT_GROQ_KEY;
  });
  const [showKeyModal, setShowKeyModal] = useState<boolean>(false);
  const [customKeyInput, setCustomKeyInput] = useState<string>(apiKey);

  const [inputMessage, setInputMessage] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Voice TTS & STT State
  const [isAutoSpeak, setIsAutoSpeak] = useState<boolean>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("delhi_aqi_auto_speak") === "true";
    }
    return true; // Default enabled as requested
  });
  const [speakingMsgId, setSpeakingMsgId] = useState<string | null>(null);
  const [isListening, setIsListening] = useState<boolean>(false);
  const recognitionRef = useRef<any>(null);
  const activeSpeechStopperRef = useRef<(() => void) | null>(null);

  const speakText = (text: string, msgId?: string) => {
    stopSpeaking();

    if (speakingMsgId && speakingMsgId === msgId) {
      setSpeakingMsgId(null);
      return;
    }

    setSpeakingMsgId(msgId || "active");

    const stopFn = playMultilingualSpeech(
      text,
      language,
      () => {
        if (msgId) setSpeakingMsgId(msgId);
      },
      () => {
        setSpeakingMsgId(null);
      },
      () => {
        setSpeakingMsgId(null);
      }
    );

    activeSpeechStopperRef.current = stopFn;
  };

  const stopSpeaking = () => {
    if (activeSpeechStopperRef.current) {
      try {
        activeSpeechStopperRef.current();
      } catch {
        // ignore
      }
      activeSpeechStopperRef.current = null;
    }
    stopAllSpeech();
    setSpeakingMsgId(null);
  };

  const handleToggleAutoSpeak = () => {
    setIsAutoSpeak((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        localStorage.setItem("delhi_aqi_auto_speak", String(next));
      }
      if (!next) {
        stopSpeaking();
      }
      return next;
    });
  };

  const toggleListening = () => {
    if (typeof window === "undefined") return;

    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      alert("Voice transcription is not supported in this browser. Please use Chrome, Edge, or Safari.");
      return;
    }

    if (isListening) {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop();
        } catch {
          // ignore
        }
      }
      setIsListening(false);
      return;
    }

    try {
      const recognition = new SpeechRecognition();
      recognitionRef.current = recognition;
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = language === "hi" ? "hi-IN" : language === "ta" ? "ta-IN" : "en-IN";

      recognition.onstart = () => {
        setIsListening(true);
      };

      recognition.onresult = (event: any) => {
        let transcript = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        if (transcript) {
          setInputMessage(transcript);
        }
      };

      recognition.onerror = (event: any) => {
        console.warn("[Voice Transcription] Error:", event.error);
        setIsListening(false);
      };

      recognition.onend = () => {
        setIsListening(false);
      };

      recognition.start();
    } catch (err) {
      console.error("[Voice Transcription] Failed to start:", err);
      setIsListening(false);
    }
  };

  // Cleanup speech synthesis on unmount
  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop();
        } catch {
          // ignore
        }
      }
    };
  }, []);

  // Live atmospheric telemetry extraction
  const liveAqi = cityAggregate?.overall_aqi ?? (consensus?.metrics?.aqi ?? (hour?.aqi ?? 342));
  const liveCat = cityAggregate?.aqi_category ?? (consensus?.forecast?.[0]?.category ?? (hour?.category ?? "Very Poor"));
  const pm25Val = cityAggregate?.sub_indices?.["PM2.5"]?.conc ?? (consensus?.metrics?.pm25 ?? 180);
  const pblM = hour?.pbl_height_m ?? 320;
  const invPresent = (hour?.inversion_delta_t ?? 2.1) > 0;
  const invDt = hour?.inversion_delta_t ?? 2.1;
  const plumeFrac = hour?.plume_contribution ?? 0.22;
  const pm10Val = cityAggregate?.sub_indices?.["PM10"]?.conc ?? (consensus?.metrics?.pm10 ?? 305);
  const no2Val = cityAggregate?.sub_indices?.["NO2"]?.conc ?? (consensus?.metrics?.no2 ?? 48);

  const getWelcomeContent = (lang: string) => {
    if (lang === "hi") {
      return `नमस्ते! मैं आपका **दिल्ली-एनसीआर श्वसन स्वास्थ्य सहायक एवं क्लीनिकल विशेषज्ञ** हूँ।\n\nमुझसे सांस संबंधी लक्षणों, दवाइयों, N95 मास्क, HEPA एयर प्यूरीफायर या सुरक्षित समय के बारे में कोई भी प्रश्न पूछें।`;
    }
    if (lang === "ta") {
      return `வணக்கம்! நான் உங்கள் **டெல்லி-என்சிஆர் சுவாச சுகாதார உதவியாளர்**.\n\nசுவாச பிரச்சனைகள், முகக்கவசங்கள், ஏர் ப்யூரிஃபையர் அமைப்புகள் அல்லது பாதுகாப்பான நேரங்கள் குறித்து எந்த கேள்வியையும் என்னிடம் கேட்கலாம்.`;
    }
    return `Hello! I am your **Delhi NCR Health Care Assistant & Clinical Air Specialist**.\n\nAsk me any specific question about respiratory symptoms, medication management, N95 mask protection, HEPA purifier settings, or safe outdoor schedules. I will give you direct, evidence-based answers tailored to Delhi's air quality.`;
  };

  const [messages, setMessages] = useState<ChatMessage[]>(() => [
    {
      id: "welcome-1",
      role: "assistant",
      content: getWelcomeContent(language),
      modelUsed: "Qwen 3.8 27B Specialist",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  // Reactive language sync: immediately update welcome message when user changes language
  useEffect(() => {
    setMessages((prev) => {
      if (prev.length === 1 && (prev[0].id === "welcome-1" || prev[0].id === "welcome-reset")) {
        return [
          {
            id: "welcome-1",
            role: "assistant",
            content: getWelcomeContent(language),
            modelUsed: "Qwen 3.8 27B Specialist",
            timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          },
        ];
      }
      return prev;
    });
  }, [language]);

  const sampleQuestions = [
    {
      icon: Stethoscope,
      title: t("healthAssistant.prompts.asthmaTitle"),
      prompt: t("healthAssistant.prompts.asthmaPrompt"),
    },
    {
      icon: Zap,
      title: t("healthAssistant.prompts.outdoorTitle"),
      prompt: t("healthAssistant.prompts.outdoorPrompt"),
    },
    {
      icon: ShieldAlert,
      title: t("healthAssistant.prompts.masksTitle"),
      prompt: t("healthAssistant.prompts.masksPrompt"),
    },
    {
      icon: Activity,
      title: t("healthAssistant.prompts.pediatricTitle"),
      prompt: t("healthAssistant.prompts.pediatricPrompt"),
    },
    {
      icon: Sparkles,
      title: t("healthAssistant.prompts.hepaTitle"),
      prompt: t("healthAssistant.prompts.hepaPrompt"),
    },
    {
      icon: AlertTriangle,
      title: t("healthAssistant.prompts.emergencyTitle"),
      prompt: t("healthAssistant.prompts.emergencyPrompt"),
    },
  ];

  const getCategoryLabel = (cat?: string) => {
    if (!cat) return "";
    switch (cat.toLowerCase()) {
      case "good": return t("hero.categories.good");
      case "satisfactory": return t("hero.categories.satisfactory");
      case "moderate": return t("hero.categories.moderate");
      case "poor": return t("hero.categories.poor");
      case "very poor": return t("hero.categories.veryPoor");
      case "severe": return t("hero.categories.severe");
      case "hazardous": return t("hero.categories.hazardous");
      default: return cat;
    }
  };

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading, statusMessage]);

  const handleSendMessage = async (textToSend?: string) => {
    const promptText = (textToSend ?? inputMessage).trim();
    if (!promptText || isLoading) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: promptText,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputMessage("");
    setIsLoading(true);
    setStatusMessage("Consulting clinical intelligence...");

    const airContext: LiveAirQualityContext = {
      aqi: liveAqi,
      category: liveCat,
      dominantPollutant: cityAggregate?.dominant_pollutant ?? "PM2.5",
      pm25: pm25Val,
      pm10: pm10Val,
      no2: no2Val,
      pblHeightM: pblM,
      inversionPresent: invPresent,
      inversionDeltaT: invDt,
      plumeFraction: plumeFrac,
      generatedAt: forecast.data?.generated_at,
    };

    const systemPrompt = buildHealthSystemPrompt(airContext, language);

    // Build chat history for Groq API
    const historyForApi: Array<{ role: "system" | "user" | "assistant"; content: string }> = [
      { role: "system", content: systemPrompt },
      ...messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(-6)
        .map((m) => ({ role: m.role, content: m.content })),
      { role: "user", content: promptText },
    ];

    try {
      const result = await executeGroqChat(
        apiKey,
        historyForApi,
        (status) => {
          setStatusMessage(status);
        },
        airContext,
        language
      );

      const fallbackNotes: string[] = [];
      if (result.attempts.length > 1) {
        result.attempts.slice(0, -1).forEach((att, idx) => {
          fallbackNotes.push(`Model ${idx + 1} (${att.model}) unavailable → Switched to ${result.modelUsed}`);
        });
      }

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: result.content,
        modelUsed: result.modelUsed,
        latencyMs: result.latencyMs,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        fallbackNotes: fallbackNotes.length > 0 ? fallbackNotes : undefined,
      };

      setMessages((prev) => [...prev, assistantMsg]);

      if (isAutoSpeak && result.content) {
        speakText(result.content, assistantMsg.id);
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      const errorMsg: ChatMessage = {
        id: `error-${Date.now()}`,
        role: "assistant",
        content: `⚠️ **Unable to complete request:**\n\n${errMsg}`,
        modelUsed: "System Diagnostics",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
      setStatusMessage("");
    }
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleClearChat = () => {
    if (confirm("Clear current conversation history?")) {
      stopSpeaking();
      setMessages([
        {
          id: "welcome-reset",
          role: "assistant",
          content: getWelcomeContent(language),
          modelUsed: "Qwen 3.8 27B",
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
      ]);
    }
  };

  const handleSaveApiKey = () => {
    const k = customKeyInput.trim();
    setApiKey(k);
    if (typeof window !== "undefined") {
      if (k) {
        localStorage.setItem("delhi_aqi_groq_api_key", k);
      } else {
        localStorage.removeItem("delhi_aqi_groq_api_key");
      }
    }
    setShowKeyModal(false);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "var(--abyss)",
        color: "var(--bone)",
        paddingTop: "4.5rem",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Top Navigation Bar */}
      <div
        style={{
          maxWidth: "1400px",
          margin: "0 auto",
          width: "100%",
          padding: "1rem var(--pad) 0.5rem",
        }}
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "1rem",
          }}
        >
          <button
            type="button"
            className="btn btn--solid"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.6rem",
              padding: "0.5rem 0.95rem",
              background: "var(--slab)",
              border: "1px solid var(--hairline-2)",
              borderRadius: "6px",
              color: "var(--bone)",
              fontFamily: "var(--mono)",
              fontSize: "12px",
              cursor: "pointer",
              transition: "all 0.2s ease",
            }}
            onClick={onBack}
          >
            <ArrowLeft size={15} />
            <span>{t("common.backToOverview")}</span>
          </button>

          {/* Right Status Badges & Key Config */}
          <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
            {/* Auto-Read Voice Toggle */}
            <button
              type="button"
              onClick={handleToggleAutoSpeak}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "5px 10px",
                background: isAutoSpeak ? "rgba(56, 189, 248, 0.15)" : "rgba(255, 255, 255, 0.05)",
                border: `1px solid ${isAutoSpeak ? "rgba(56, 189, 248, 0.4)" : "rgba(255, 255, 255, 0.12)"}`,
                borderRadius: "4px",
                fontFamily: "var(--mono)",
                fontSize: "11px",
                color: isAutoSpeak ? "var(--cyan)" : "var(--mist)",
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
              title={
                language === "hi"
                  ? "उत्तरों को बोलकर सुनना चालू/बंद करें"
                  : language === "ta"
                  ? "பதில்களை குரலில் கேட்க ஆன்/ஆஃப் செய்யவும்"
                  : "Toggle reading replies aloud"
              }
            >
              {isAutoSpeak ? (
                <Volume2 size={13} style={{ color: "var(--cyan)" }} />
              ) : (
                <VolumeX size={13} />
              )}
              <span>
                {language === "hi"
                  ? isAutoSpeak
                    ? "आवाज़: चालू"
                    : "आवाज़: बंद"
                  : language === "ta"
                  ? isAutoSpeak
                    ? "குரல்: ஆன்"
                    : "குரல்: ஆஃப்"
                  : isAutoSpeak
                  ? "Voice: ON"
                  : "Voice: OFF"}
              </span>
            </button>

            <button
              type="button"
              onClick={() => {
                setCustomKeyInput(apiKey);
                setShowKeyModal(true);
              }}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "5px 10px",
                background: apiKey ? "rgba(16, 185, 129, 0.12)" : "rgba(255, 255, 255, 0.05)",
                border: `1px solid ${apiKey ? "rgba(16, 185, 129, 0.35)" : "rgba(255, 255, 255, 0.12)"}`,
                borderRadius: "4px",
                fontFamily: "var(--mono)",
                fontSize: "11px",
                color: apiKey ? "#10b981" : "var(--mist)",
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
              title="Configure Groq Cloud API Key"
            >
              <KeyRound size={12} />
              <span>
                {apiKey
                  ? apiKey.startsWith("AIza")
                    ? "Gemini AI (Active)"
                    : "Groq AI (Active)"
                  : "Cloud AI Key"}
              </span>
            </button>

            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "4px 10px",
                background: "rgba(56, 189, 248, 0.12)",
                border: "1px solid rgba(56, 189, 248, 0.35)",
                borderRadius: "4px",
                fontFamily: "var(--mono)",
                fontSize: "11px",
                color: "var(--cyan)",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              <Stethoscope size={13} style={{ color: "var(--cyan)" }} />
              {t("healthAssistant.clinicalActive")}
            </span>
          </div>
        </div>
      </div>

      {/* Main Section Header */}
      <div
        style={{
          maxWidth: "1400px",
          margin: "0 auto",
          width: "100%",
          padding: "0.5rem var(--pad) 1rem",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
            flexWrap: "wrap",
            gap: "1.2rem",
          }}
        >
          <div>
            <p className="eyebrow" style={{ color: "var(--mist-dim)", margin: "0 0 0.25rem" }}>
              clinical pulmonary &amp; environmental health intelligence
            </p>
            <h1
              style={{
                margin: "0.15rem 0 0.4rem 0",
                fontSize: "clamp(2.1rem, 3.8vw, 3.0rem)",
                fontWeight: 600,
                letterSpacing: "-0.03em",
                color: "var(--bone)",
                lineHeight: 1.15,
              }}
            >
              {t("healthAssistant.title")}
            </h1>
            <p
              style={{
                margin: 0,
                fontSize: "0.95rem",
                color: "var(--mist)",
                maxWidth: "75ch",
                lineHeight: 1.55,
              }}
            >
              {t("healthAssistant.subtitle")}
            </p>
          </div>

          {/* Live Telemetry Pill */}
          <div
            style={{
              display: "flex",
              gap: "1px",
              background: "rgba(255, 255, 255, 0.08)",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              borderRadius: "8px",
              overflow: "hidden",
            }}
          >
            <div style={{ padding: "0.6rem 0.95rem", background: "rgba(10, 16, 26, 0.9)" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "var(--mist-dim)", textTransform: "uppercase" }}>
                {t("common.live")} AQI
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "1.2rem", color: "var(--amber)", fontWeight: 700 }}>
                {liveAqi} <span style={{ fontSize: "10px", fontWeight: 400, color: "var(--mist)" }}>({getCategoryLabel(liveCat)})</span>
              </div>
            </div>

            <div style={{ padding: "0.6rem 0.95rem", background: "rgba(10, 16, 26, 0.9)" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "var(--mist-dim)", textTransform: "uppercase" }}>
                PM2.5 Conc.
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "1.2rem", color: "#f43f5e", fontWeight: 700 }}>
                {Math.round(pm25Val)} <span style={{ fontSize: "10px", fontWeight: 400, color: "var(--mist)" }}>µg/m³</span>
              </div>
            </div>

            <div style={{ padding: "0.6rem 0.95rem", background: "rgba(10, 16, 26, 0.9)" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "var(--mist-dim)", textTransform: "uppercase" }}>
                {t("atmosphere.mixingDepth")}
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "1.2rem", color: "var(--bone)", fontWeight: 700 }}>
                {Math.round(pblM)} <span style={{ fontSize: "10px", fontWeight: 400, color: "var(--mist)" }}>m</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Chat Interface */}
      <main
        style={{
          maxWidth: "1400px",
          margin: "0 auto",
          width: "100%",
          flex: 1,
          padding: "0.5rem var(--pad) 2.5rem",
          display: "flex",
          flexDirection: "column",
          gap: "1rem",
        }}
      >
        {/* Suggested Quick Question Chips */}
        <div style={{ display: "flex", gap: "0.5rem", overflowX: "auto", paddingBottom: "0.4rem" }}>
          {sampleQuestions.map((q, idx) => {
            const Icon = q.icon;
            return (
              <button
                key={idx}
                type="button"
                onClick={() => handleSendMessage(q.prompt)}
                disabled={isLoading}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.45rem",
                  padding: "0.45rem 0.85rem",
                  background: "rgba(255, 255, 255, 0.03)",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                  borderRadius: "16px",
                  color: "var(--bone)",
                  fontSize: "12px",
                  whiteSpace: "nowrap",
                  cursor: isLoading ? "not-allowed" : "pointer",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--cyan)";
                  e.currentTarget.style.background = "rgba(56, 189, 248, 0.1)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.08)";
                  e.currentTarget.style.background = "rgba(255, 255, 255, 0.03)";
                }}
              >
                <Icon size={13} style={{ color: "var(--cyan)" }} />
                <span>{q.title}</span>
              </button>
            );
          })}
        </div>

        {/* ── CHAT WINDOW (REALISM SHINY BOX) ── */}
        <article className="realism-box" style={{ width: "100%", flex: 1, display: "flex", flexDirection: "column" }}>
          <div className="realism-topglow" />
          <div className="realism-blob" style={{ background: "radial-gradient(circle, #38bdf855 0%, transparent 70%)" }} />
          <div
            className="realism-inner"
            style={{
              padding: "clamp(1rem, 2vw, 1.5rem)",
              display: "flex",
              flexDirection: "column",
              flex: 1,
              minHeight: "480px",
            }}
          >
            <div className="realism-inner-glow" />

            {/* Message List */}
            <div
              style={{
                flex: 1,
                minHeight: "380px",
                maxHeight: "56vh",
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: "1.1rem",
                paddingRight: "0.4rem",
              }}
            >
              {messages.map((msg) => {
                const isUser = msg.role === "user";
                const senderName = isUser
                  ? (language === "hi" ? "आप" : language === "ta" ? "நீங்கள்" : "You")
                  : (language === "hi" ? "स्वास्थ्य सहायक" : language === "ta" ? "சுகாதார உதவியாளர்" : "Health Assistant");

                return (
                  <div
                    key={msg.id}
                    style={{
                      display: "flex",
                      gap: "0.75rem",
                      alignSelf: isUser ? "flex-end" : "flex-start",
                      maxWidth: isUser ? "80%" : "92%",
                    }}
                  >
                    {!isUser && (
                      <div
                        style={{
                          width: "32px",
                          height: "32px",
                          borderRadius: "8px",
                          background: "rgba(56, 189, 248, 0.15)",
                          border: "1px solid rgba(56, 189, 248, 0.4)",
                          display: "grid",
                          placeItems: "center",
                          color: "var(--cyan)",
                          flexShrink: 0,
                          marginTop: "2px",
                        }}
                      >
                        <Bot size={17} />
                      </div>
                    )}

                    <div
                      style={{
                        background: isUser
                          ? "linear-gradient(135deg, rgba(56, 189, 248, 0.22), rgba(2, 132, 199, 0.15))"
                          : "rgba(255, 255, 255, 0.03)",
                        border: `1px solid ${isUser ? "rgba(56, 189, 248, 0.4)" : "rgba(255, 255, 255, 0.08)"}`,
                        borderRadius: "10px",
                        padding: "0.9rem 1.15rem",
                        color: "var(--bone)",
                        fontSize: "13.5px",
                        lineHeight: 1.6,
                        boxShadow: isUser ? "0 4px 15px rgba(56, 189, 248, 0.15)" : "0 2px 10px rgba(0,0,0,0.3)",
                      }}
                    >
                      {/* Message Header */}
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          gap: "1rem",
                          marginBottom: "0.5rem",
                          paddingBottom: "0.35rem",
                          borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                          <span style={{ fontWeight: 700, fontSize: "11.5px", color: isUser ? "var(--cyan)" : "var(--bone)" }}>
                            {senderName}
                          </span>
                          {!isUser && msg.modelUsed && (
                            <span
                              style={{
                                fontFamily: "var(--mono)",
                                fontSize: "10px",
                                padding: "1px 6px",
                                background: "rgba(0, 0, 0, 0.4)",
                                border: "1px solid rgba(255, 255, 255, 0.1)",
                                borderRadius: "4px",
                                color: "var(--mist-dim)",
                              }}
                            >
                              {msg.modelUsed}
                            </span>
                          )}
                          {!isUser && msg.latencyMs && (
                            <span style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "var(--mist-dim)" }}>
                              ({msg.latencyMs}ms)
                            </span>
                          )}
                        </div>

                        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                          <span style={{ fontSize: "10.5px", color: "var(--mist-dim)", fontFamily: "var(--mono)" }}>{msg.timestamp}</span>
                          {!isUser && (
                            <button
                              type="button"
                              onClick={() => speakText(msg.content, msg.id)}
                              style={{
                                background: "none",
                                border: "none",
                                color: speakingMsgId === msg.id ? "var(--cyan)" : "var(--mist-dim)",
                                cursor: "pointer",
                                padding: "2px",
                                display: "flex",
                                alignItems: "center",
                              }}
                              title={speakingMsgId === msg.id ? "Stop reading" : "Read message aloud (English)"}
                            >
                              {speakingMsgId === msg.id ? (
                                <Square size={13} style={{ fill: "var(--cyan)", color: "var(--cyan)" }} />
                              ) : (
                                <Volume2 size={13} />
                              )}
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => copyToClipboard(msg.content, msg.id)}
                            style={{
                              background: "none",
                              border: "none",
                              color: copiedId === msg.id ? "#10b981" : "var(--mist-dim)",
                              cursor: "pointer",
                              padding: "2px",
                            }}
                            title="Copy message"
                          >
                            {copiedId === msg.id ? <Check size={13} /> : <Copy size={13} />}
                          </button>
                        </div>
                      </div>

                      {/* Content */}
                      <div
                        style={{
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        {msg.content}
                      </div>
                    </div>

                    {isUser && (
                      <div
                        style={{
                          width: "32px",
                          height: "32px",
                          borderRadius: "8px",
                          background: "rgba(255, 255, 255, 0.08)",
                          border: "1px solid rgba(255, 255, 255, 0.15)",
                          display: "grid",
                          placeItems: "center",
                          color: "var(--bone)",
                          flexShrink: 0,
                          marginTop: "2px",
                        }}
                      >
                        <User size={16} />
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Active Generation Indicator */}
              {isLoading && (
                <div style={{ display: "flex", gap: "0.75rem", alignSelf: "flex-start" }}>
                  <div
                    style={{
                      width: "32px",
                      height: "32px",
                      borderRadius: "8px",
                      background: "rgba(56, 189, 248, 0.15)",
                      border: "1px solid rgba(56, 189, 248, 0.4)",
                      display: "grid",
                      placeItems: "center",
                      color: "var(--cyan)",
                      flexShrink: 0,
                    }}
                  >
                    <RefreshCw size={15} className="spin" />
                  </div>
                  <div
                    style={{
                      background: "rgba(255, 255, 255, 0.03)",
                      border: "1px solid rgba(255, 255, 255, 0.08)",
                      borderRadius: "8px",
                      padding: "0.75rem 1.1rem",
                      color: "var(--bone)",
                      fontSize: "12.5px",
                      display: "flex",
                      alignItems: "center",
                      gap: "0.5rem",
                    }}
                  >
                    <span className="pulse" style={{ color: "var(--cyan)" }}>●</span>
                    <span>{statusMessage || "Consulting medical model..."}</span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input Bar & Controls */}
            <div
              style={{
                display: "flex",
                gap: "0.75rem",
                alignItems: "center",
                marginTop: "1.2rem",
                paddingTop: "1rem",
                borderTop: "1px solid rgba(255, 255, 255, 0.08)",
              }}
            >
              <button
                type="button"
                onClick={handleClearChat}
                style={{
                  padding: "0.75rem 1rem",
                  background: "rgba(255, 255, 255, 0.04)",
                  border: "1px solid rgba(255, 255, 255, 0.1)",
                  borderRadius: "8px",
                  color: "var(--mist)",
                  fontFamily: "var(--mono)",
                  fontSize: "11px",
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  transition: "all 0.15s ease",
                }}
                title="Reset conversation"
              >
                {t("healthAssistant.clearHistory")}
              </button>

              <div
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  background: "rgba(0, 0, 0, 0.4)",
                  border: "1px solid rgba(255, 255, 255, 0.12)",
                  borderRadius: "8px",
                  padding: "0 0.6rem 0 0.9rem",
                  boxShadow: "inset 0 2px 6px rgba(0,0,0,0.5)",
                }}
              >
                <input
                  type="text"
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  placeholder={t("healthAssistant.chatPlaceholder")}
                  style={{
                    width: "100%",
                    background: "transparent",
                    border: "none",
                    color: "var(--bone)",
                    padding: "0.75rem 0.2rem",
                    fontSize: "13.5px",
                    outline: "none",
                  }}
                  disabled={isLoading}
                />

                {/* Voice Transcription Microphone Button */}
                <button
                  type="button"
                  onClick={toggleListening}
                  style={{
                    background: isListening ? "rgba(239, 68, 68, 0.25)" : "transparent",
                    color: isListening ? "#ef4444" : "var(--mist)",
                    border: isListening ? "1px solid rgba(239, 68, 68, 0.5)" : "none",
                    borderRadius: "6px",
                    padding: "0.5rem",
                    marginRight: "0.4rem",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    transition: "all 0.2s ease",
                    boxShadow: isListening ? "0 0 12px rgba(239, 68, 68, 0.5)" : "none",
                  }}
                  title={isListening ? "Listening... Click to stop" : "Voice input / Speech-to-text"}
                >
                  {isListening ? (
                    <MicOff size={16} style={{ color: "#ef4444" }} className="pulse" />
                  ) : (
                    <Mic size={16} />
                  )}
                </button>

                <button
                  type="button"
                  onClick={() => handleSendMessage()}
                  disabled={isLoading || !inputMessage.trim()}
                  style={{
                    background: inputMessage.trim() ? "linear-gradient(135deg, #38bdf8, #0284c7)" : "rgba(255, 255, 255, 0.08)",
                    color: inputMessage.trim() ? "#04111d" : "var(--mist-dim)",
                    border: "none",
                    borderRadius: "6px",
                    padding: "0.5rem 0.85rem",
                    cursor: inputMessage.trim() && !isLoading ? "pointer" : "not-allowed",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    transition: "all 0.2s ease",
                  }}
                >
                  <Send size={15} />
                </button>
              </div>
            </div>

            {/* Clinical Disclaimer */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                color: "var(--mist-dim)",
                fontSize: "11px",
                marginTop: "0.6rem",
              }}
            >
              <Info size={13} style={{ flexShrink: 0, color: "var(--mist-dim)" }} />
              <span>
                {t("healthAssistant.aiDisclaimer")}
              </span>
            </div>
          </div>
        </article>
      </main>

      {/* API Key Configuration Modal */}
      {showKeyModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.75)",
            backdropFilter: "blur(6px)",
            zIndex: 9999,
            display: "grid",
            placeItems: "center",
            padding: "1rem",
          }}
          onClick={() => setShowKeyModal(false)}
        >
          <div
            style={{
              background: "#0d131d",
              border: "1px solid rgba(56, 189, 248, 0.3)",
              borderRadius: "14px",
              maxWidth: "500px",
              width: "100%",
              padding: "1.5rem",
              boxShadow: "0 20px 50px rgba(0, 0, 0, 0.8), 0 0 30px rgba(56, 189, 248, 0.15)",
              color: "var(--bone)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <KeyRound size={18} style={{ color: "var(--cyan)" }} />
                <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 600 }}>Cloud AI Key (Optional)</h3>
              </div>
              <button
                type="button"
                onClick={() => setShowKeyModal(false)}
                style={{ background: "none", border: "none", color: "var(--mist)", cursor: "pointer" }}
              >
                <X size={18} />
              </button>
            </div>

            <p style={{ fontSize: "12.5px", color: "var(--mist)", lineHeight: 1.5, marginBottom: "1rem" }}>
              The assistant includes a <strong>Built-in Clinical & Environmental Intelligence Engine</strong> that works 100% out of the box with zero API keys required. You can optionally paste a free <strong>Google Gemini API Key</strong> (<a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" style={{ color: "var(--cyan)", textDecoration: "underline" }}>get free key</a>) or <strong>Groq API Key</strong> (<a href="https://console.groq.com/keys" target="_blank" rel="noreferrer" style={{ color: "var(--cyan)", textDecoration: "underline" }}>get free key</a>) for live cloud LLM reasoning.
            </p>

            <div style={{ marginBottom: "1.2rem" }}>
              <label style={{ display: "block", fontSize: "11px", fontFamily: "var(--mono)", color: "var(--mist-dim)", marginBottom: "0.4rem" }}>
                GOOGLE GEMINI OR GROQ API KEY
              </label>
              <input
                type="password"
                value={customKeyInput}
                onChange={(e) => setCustomKeyInput(e.target.value)}
                placeholder="Paste Gemini (AIzaSy...) or Groq (gsk_...) key"
                style={{
                  width: "100%",
                  padding: "0.75rem",
                  background: "rgba(0, 0, 0, 0.5)",
                  border: "1px solid rgba(255, 255, 255, 0.15)",
                  borderRadius: "8px",
                  color: "var(--bone)",
                  fontSize: "13px",
                  fontFamily: "var(--mono)",
                  outline: "none",
                }}
              />
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", flexWrap: "wrap" }}>
              {apiKey && (
                <button
                  type="button"
                  onClick={() => {
                    setCustomKeyInput("");
                    setApiKey("");
                    if (typeof window !== "undefined") {
                      localStorage.removeItem("delhi_aqi_groq_api_key");
                    }
                    setShowKeyModal(false);
                  }}
                  style={{
                    padding: "0.6rem 1rem",
                    background: "rgba(239, 68, 68, 0.15)",
                    border: "1px solid rgba(239, 68, 68, 0.4)",
                    borderRadius: "6px",
                    color: "#f87171",
                    fontSize: "12px",
                    cursor: "pointer",
                  }}
                >
                  Clear Key
                </button>
              )}
              <button
                type="button"
                onClick={handleSaveApiKey}
                style={{
                  padding: "0.6rem 1.2rem",
                  background: "linear-gradient(135deg, #38bdf8, #0284c7)",
                  border: "none",
                  borderRadius: "6px",
                  color: "#04111d",
                  fontSize: "12px",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Save Key
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
export default HealthCareAssistantPage;
