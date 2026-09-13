/**
 * Multilingual Translation Dictionary for the NCR·72 Alert System
 * Supports English (en), Hindi (hi), and Tamil (ta)
 */

export type AlertLanguage = "en" | "hi" | "ta";

export interface AlertTranslationStrings {
  alertsTitle: string;
  alertsSubtitle: string;
  activeAlerts: string;
  earlierAlerts: string;
  summaryActive: string;
  summaryToday: string;
  summaryCritical: string;
  summaryUpdated: string;
  noActiveAlertsTitle: string;
  noActiveAlertsDesc: string;
  markAllRead: string;
  alertSettings: string;
  filterAll: string;
  filterCritical: string;
  filterHigh: string;
  filterModerate: string;
  viewDetails: string;
  viewOnMap: string;
  checkExposure: string;
  checkForecast: string;
  backToOverview: string;
  impactLevel: string;
  recommendedAction: string;
  keyPollutants: string;
  potentialSources: string;
  observedData: string;
  predictedData: string;
  possibleSource: string;
  recommendation: string;
  detectedAt: string;
  lastUpdated: string;
  location: string;
  statusActive: string;
  statusResolved: string;
  minAgo: string;
  hoursAgo: string;
  justNow: string;
  saveSettings: string;
  close: string;
  dangerLabel: string;
  protocolLabel: string;
}

export const ALERT_TRANSLATIONS: Record<AlertLanguage, AlertTranslationStrings> = {
  en: {
    alertsTitle: "ENVIRONMENTAL ALERTS",
    alertsSubtitle: "Real-time, actionable air quality and pollution advisories for Delhi-NCR",
    activeAlerts: "Active Alerts",
    earlierAlerts: "Earlier & Resolved Alerts",
    summaryActive: "ACTIVE ALERTS",
    summaryToday: "NEW TODAY",
    summaryCritical: "CRITICAL",
    summaryUpdated: "LAST UPDATED",
    noActiveAlertsTitle: "You're All Clear",
    noActiveAlertsDesc: "No active environmental warnings or critical anomalies detected across your area.",
    markAllRead: "Mark all as read",
    alertSettings: "Alert Settings",
    filterAll: "All Categories",
    filterCritical: "Critical / Severe",
    filterHigh: "High",
    filterModerate: "Moderate",
    viewDetails: "View Full Analysis",
    viewOnMap: "View on Map",
    checkExposure: "Check Personal Exposure",
    checkForecast: "View 72h Outlook",
    backToOverview: "← Back to Live Overview",
    impactLevel: "Health Impact Level",
    recommendedAction: "Actionable Guidance",
    keyPollutants: "Primary Pollutants",
    potentialSources: "Potential Contributing Factors",
    observedData: "Observed Live Telemetry",
    predictedData: "Prognostic Prediction",
    possibleSource: "Nearby Spatial Source",
    recommendation: "Protective Measures",
    detectedAt: "First Detected",
    lastUpdated: "Last Verified",
    location: "Monitored Zone",
    statusActive: "ACTIVE ADVISORY",
    statusResolved: "RESOLVED / NORMALIZED",
    minAgo: "min ago",
    hoursAgo: "hrs ago",
    justNow: "Just now",
    saveSettings: "Save Preferences",
    close: "Close",
    dangerLabel: "DANGER",
    protocolLabel: "RECOMMENDED PROTOCOL:",
  },
  hi: {
    alertsTitle: "पर्यावरण अलर्ट और चेतावनियाँ",
    alertsSubtitle: "दिल्ली-एनसीआर के लिए वास्तविक समय वायु गुणवत्ता और स्वास्थ्य सलाह",
    activeAlerts: "सक्रिय अलर्ट",
    earlierAlerts: "पिछले और सुलझे हुए अलर्ट",
    summaryActive: "सक्रिय अलर्ट",
    summaryToday: "आज के नए",
    summaryCritical: "गंभीर चेतावनियाँ",
    summaryUpdated: "अंतिम अपडेट",
    noActiveAlertsTitle: "स्थिति सामान्य और सुरक्षित है",
    noActiveAlertsDesc: "आपके क्षेत्र में वर्तमान में कोई गंभीर पर्यावरण चेतावनी सक्रिय नहीं है।",
    markAllRead: "सभी को पढ़ा हुआ चिह्नित करें",
    alertSettings: "अलर्ट सेटिंग्स",
    filterAll: "सभी श्रेणियां",
    filterCritical: "अत्यधिक गंभीर",
    filterHigh: "उच्च स्तर",
    filterModerate: "मध्यम स्तर",
    viewDetails: "विस्तृत विवरण देखें",
    viewOnMap: "मानचित्र पर देखें",
    checkExposure: "व्यक्तिगत जोखिम जांचें",
    checkForecast: "72 घंटे का पूर्वानुमान",
    backToOverview: "← मुख्य डैशबोर्ड पर लौटें",
    impactLevel: "स्वास्थ्य प्रभाव स्तर",
    recommendedAction: "अनुशंसित सुरक्षा उपाय",
    keyPollutants: "मुख्य प्रदूषक तत्व",
    potentialSources: "संभावित योगदानकर्ता कारक",
    observedData: "वर्तमान लाइव आंकड़े",
    predictedData: "पूर्वानुमान आंकड़े",
    possibleSource: "निकटवर्ती स्रोत",
    recommendation: "सुरक्षात्मक सलाह",
    detectedAt: "पहला पता चला",
    lastUpdated: "अंतिम सत्यापन",
    location: "निगरानी क्षेत्र",
    statusActive: "सक्रिय चेतावनी",
    statusResolved: "सामान्य हो गया",
    minAgo: "मिनट पहले",
    hoursAgo: "घंटे पहले",
    justNow: "अभी-अभी",
    saveSettings: "प्राथमिकताएं सहेजें",
    close: "बंद करें",
    dangerLabel: "खतरा",
    protocolLabel: "अनुशंसित प्रोटोकॉल:",
  },
  ta: {
    alertsTitle: "சுற்றுச்சூழல் எச்சரிக்கைகள்",
    alertsSubtitle: "தில்லி-என்சிஆருக்கான நிகழ்நேர காற்றுத் தரம் மற்றும் பாதுகாப்பு வழிகாட்டல்",
    activeAlerts: "செயலில் உள்ள எச்சரிக்கைகள்",
    earlierAlerts: "முந்தைய மற்றும் தீர்க்கப்பட்ட எச்சரிக்கைகள்",
    summaryActive: "செயலில் உள்ளவை",
    summaryToday: "இன்றைய புதியவை",
    summaryCritical: "தீவிர எச்சரிக்கைகள்",
    summaryUpdated: "கடைசியாக புதுப்பிக்கப்பட்டது",
    noActiveAlertsTitle: "நிலைமை பாதுகாப்பாக உள்ளது",
    noActiveAlertsDesc: "உங்கள் பகுதியில் எந்தவொரு தீவிர சுற்றுச்சூழல் எச்சரிக்கையும் தற்போது இல்லை.",
    markAllRead: "அனைத்தையும் படித்ததாகக் குறிக்கவும்",
    alertSettings: "எச்சரிக்கை அமைப்புகள்",
    filterAll: "அனைத்து பிரிவுகளும்",
    filterCritical: "மிகக் கடுமையானது",
    filterHigh: "உயர் எச்சரிக்கை",
    filterModerate: "மிதமான எச்சரிக்கை",
    viewDetails: "முழு விவரங்களைப் பார்க்கவும்",
    viewOnMap: "வரைபடத்தில் காண்க",
    checkExposure: "தனிநபர் பாதிப்பைச் சரிபார்க்கவும்",
    checkForecast: "72 மணிநேர முன்னறிவிப்பு",
    backToOverview: "← முதன்மைப் பக்கத்திற்குத் திரும்பு",
    impactLevel: "சுகாதார பாதிப்பு நிலை",
    recommendedAction: "பரிந்துரைக்கப்பட்ட பாதுகாப்பு நடவடிக்கை",
    keyPollutants: "முக்கிய மாசுபடுத்திகள்",
    potentialSources: "சாத்தியமான காரணிகள்",
    observedData: "நேரலை அவதானிப்புகள்",
    predictedData: "முன்னறிவிப்பு தரவு",
    possibleSource: "அருகிலுள்ள மூலங்கள்",
    recommendation: "பாதுகாப்பு வழிகாட்டல்",
    detectedAt: "முதலில் கண்டறியப்பட்டது",
    lastUpdated: "கடைசி சரிபார்ப்பு",
    location: "கண்காணிக்கப்படும் பகுதி",
    statusActive: "செயலில் உள்ள எச்சரிக்கை",
    statusResolved: "சீரானது / முடிவடைந்தது",
    minAgo: "நிமிடங்களுக்கு முன்",
    hoursAgo: "மணிநேரங்களுக்கு முன்",
    justNow: "சற்றுமுன்",
    saveSettings: "அமைப்புகளைச் சேமிக்கவும்",
    close: "மூடு",
    dangerLabel: "ஆபத்து",
    protocolLabel: "பரிந்துரைக்கப்பட்ட நெறிமுறை:",
  },
};
