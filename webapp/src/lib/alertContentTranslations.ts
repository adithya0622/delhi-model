/**
 * Multilingual Alert Body Content Translations
 * Provides translated title, summary, description, recommendedAction, sensitiveGroupAction
 * for each alert rule (A through G) in Hindi and Tamil.
 * English is the default fallback already in alertsEngine.ts.
 */

export type AlertLang = "en" | "hi" | "ta";

export interface AlertBodyStrings {
  // Rule A: Regional AQI
  severeTitle: string;
  severeSummary: (aqi: number) => string;
  severeDesc: (pm25: number) => string;
  severeLocation: string;
  severeAction: string;
  severeSensitive: string;
  severeSourceLabel: string;
  severeSourceDetail: string;

  veryPoorTitle: string;
  veryPoorSummary: (aqi: number) => string;
  veryPoorDesc: (pm25: number) => string;
  veryPoorLocation: string;
  veryPoorAction: string;
  veryPoorSensitive: string;
  veryPoorSourceLabel: string;
  veryPoorSourceDetail: string;

  poorTitle: string;
  poorSummary: (aqi: number) => string;
  poorDesc: (pm25: number) => string;
  poorLocation: string;
  poorAction: string;
  poorSensitive: string;
  poorSourceLabel: string;
  poorSourceDetail: string;

  // Rule B: Station Hotspot
  hotspotTitle: (name: string) => string;
  hotspotSummary: (name: string, aqi: number) => string;
  hotspotDesc: (name: string) => string;
  hotspotAction: string;
  hotspotSensitive: string;
  hotspotSourceLabel: string;
  hotspotSourceDetail: (uid: string) => string;

  // Rule C: Rapid Rise
  rapidTitle: string;
  rapidSummary: (prev: number, curr: number, delta: number) => string;
  rapidDesc: string;
  rapidLocation: string;
  rapidAction: string;
  rapidSensitive: string;
  rapidSourceLabel: string;
  rapidSourceDetail: (delta: number) => string;

  // Rule D: Industrial
  industrialTitle: string;
  industrialSummary: (name: string) => string;
  industrialDesc: (windDir: string, windSpd: number) => string;
  industrialAction: string;
  industrialSensitive: string;
  industrialSourceLabel: string;
  industrialSourceDetail: (sector: string) => string;

  // Rule E: Fire/Smoke
  fireTitle: string;
  fireSummary: (count: number) => string;
  fireDesc: (frp: number, state: string) => string;
  fireAction: string;
  fireSensitive: string;
  fireSourceLabel: string;
  fireSourceDetail: string;

  // Rule F: Forecast Deterioration
  forecastTitle: string;
  forecastSummary: (current: number, predicted: number) => string;
  forecastDesc: string;
  forecastLocation: string;
  forecastAction: string;
  forecastSensitive: string;
  forecastSourceLabel: string;
  forecastSourceDetail: (predicted: number, time: string) => string;

  // Rule G: Exposure
  exposureTitle: string;
  exposureSummary: string;
  exposureDesc: (pm25: number) => string;
  exposureLocation: string;
  exposureAction: string;
  exposureSensitive: string;
  exposureSourceLabel: string;
  exposureSourceDetail: string;

  // Historical
  histTitle1: string;
  histSummary1: string;
  histDesc1: string;
  histLocation1: string;
  histAction1: string;
  histSensitive1: string;
  histSourceLabel1: string;
  histSourceDetail1: string;

  histTitle2: string;
  histSummary2: string;
  histDesc2: string;
  histLocation2: string;
  histAction2: string;
  histSensitive2: string;
  histSourceLabel2: string;
  histSourceDetail2: string;
}

export const ALERT_BODY: Record<AlertLang, AlertBodyStrings> = {
  en: {
    severeTitle: "Severe Air Quality Emergency Advisory",
    severeSummary: (aqi) => `Regional AQI has reached ${aqi} (Severe). Air pollution is dangerous across Delhi-NCR.`,
    severeDesc: (pm25) => `Atmospheric monitoring stations indicate severe pollutant concentration across the National Capital Region. Microscopic particulate matter (PM2.5 at ${pm25} µg/m³) is currently 8× above CPCB national safety thresholds.`,
    severeLocation: "Delhi-NCR Regional Network (All 11 Districts)",
    severeAction: "Avoid all outdoor physical activity. Keep windows and doors tightly sealed. Run indoor HEPA air filtration if available.",
    severeSensitive: "Children, senior citizens, and people with respiratory or cardiac ailments should strictly remain indoors and have prescribed medication accessible.",
    severeSourceLabel: "CPCB Multi-Station Grid",
    severeSourceDetail: "Confirmed by 43 continuous ambient air quality monitoring stations.",

    veryPoorTitle: "Very Poor Air Quality Alert",
    veryPoorSummary: (aqi) => `Air quality has reached a very poor level across Delhi-NCR (AQI ${aqi}).`,
    veryPoorDesc: (pm25) => `Sustained high particulate density detected across the urban airshed. PM2.5 levels are currently averaging ${pm25} µg/m³, which causes prolonged respiratory discomfort upon active outdoor exposure.`,
    veryPoorLocation: "Delhi-NCR Urban Metropolitan Area",
    veryPoorAction: "Minimize prolonged outdoor exertion, especially during morning and evening rush hours. Wear an N95 mask if commuting.",
    veryPoorSensitive: "Persons with asthma or cardiovascular conditions should limit outdoor exposure and monitor peak airflow symptoms.",
    veryPoorSourceLabel: "CPCB / DPCC Real-Time Telemetry",
    veryPoorSourceDetail: "Verified against multi-provider ambient monitoring network.",

    poorTitle: "Poor Air Quality Advisory",
    poorSummary: (aqi) => `Air quality is in the Poor category (AQI ${aqi}) in Delhi-NCR.`,
    poorDesc: (pm25) => `Moderate-to-poor dispersion conditions are causing a buildup of fine particulates (PM2.5: ${pm25} µg/m³). Outdoor air is unfavorable for sensitive groups.`,
    poorLocation: "Delhi-NCR Metropolitan Area",
    poorAction: "Reduce strenuous outdoor activities. Consider wearing a protective mask during congested road commutes.",
    poorSensitive: "Sensitive individuals should take regular breaks and avoid high-traffic roads.",
    poorSourceLabel: "CAAQMS Live Telemetry",
    poorSourceDetail: "Aggregated across ambient monitoring network.",

    hotspotTitle: (name) => `Localized Hotspot Spike: ${name}`,
    hotspotSummary: (name, aqi) => `Air pollution has surged to critical levels at ${name} (AQI ${aqi}).`,
    hotspotDesc: (name) => `Continuous ambient monitoring at ${name} registered elevated particulate concentration. Local atmospheric conditions and dense traffic/industrial corridors in the vicinity are limiting vertical dispersion.`,
    hotspotAction: "Residents in and around this micro-zone should avoid morning and evening jogs and keep ventilation closed.",
    hotspotSensitive: "High risk of acute breathing irritation. Avoid outdoor exposure in this sector.",
    hotspotSourceLabel: "Local CAAQMS Sensor",
    hotspotSourceDetail: (uid) => `Direct sensor feed from Station UID: ${uid}.`,

    rapidTitle: "Rapid Pollution Surge Detected",
    rapidSummary: (prev, curr, delta) => `PM2.5 increased significantly in the last hour (${prev} → ${curr} µg/m³, +${delta}%).`,
    rapidDesc: "A rapid influx of fine particulate matter was recorded within a short time window. Rapid rises typically indicate boundary-layer compression or localized heavy traffic congestion.",
    rapidLocation: "Delhi-NCR Central Airshed",
    rapidAction: "Expect sudden deterioration in outdoor air clarity. Postpone non-essential outdoor errands until particulate levels stabilize.",
    rapidSensitive: "Vulnerable individuals should avoid outdoor exposure while particulate surge is underway.",
    rapidSourceLabel: "Derivative Rate-of-Change Tracker",
    rapidSourceDetail: (delta) => `PM2.5 rate of increase exceeded +${delta}% per hour threshold.`,

    industrialTitle: "Potential Industrial Zone Emission Influence",
    industrialSummary: (name) => `Potential industrial emission influence detected near ${name} cluster.`,
    industrialDesc: (windDir, windSpd) => `Spatial proximity and local wind trajectory (${windDir} at ${windSpd} m/s) indicate potential downwind particulate influence from nearby manufacturing and processing facilities in this industrial belt.`,
    industrialAction: "Residents living downwind of industrial pockets should keep windows facing industrial corridors closed during night and early morning hours.",
    industrialSensitive: "Be aware of chemical or sulfurous odors. Use carbon/HEPA indoor filters if residing close to the cluster.",
    industrialSourceLabel: "Delhi Industrial Cluster Registry (CPCB Tier 1)",
    industrialSourceDetail: (sector) => `Sector: ${sector}. Spatial correlation assessed downwind.`,

    fireTitle: "Upstream Fire & Biomass Smoke Activity Detected",
    fireSummary: (count) => `Satellite detection identified ${count} active thermal hotspot(s) in upstream agricultural belts.`,
    fireDesc: (frp, state) => `NASA FIRMS VIIRS satellite sensors detected active biomass burn signatures (Peak FRP: ${frp} MW in ${state}). Regional 850 hPa wind trajectories indicate potential atmospheric smoke influx toward Delhi-NCR.`,
    fireAction: "Expect hazy skies and reduced visibility during late evening and dawn. Limit outdoor activities during early morning.",
    fireSensitive: "Smoke particles contain fine organic carbon. Use tight-fitting N95 masks if outdoors.",
    fireSourceLabel: "NASA FIRMS Satellite Telemetry",
    fireSourceDetail: "Confirmed by VIIRS/MODIS thermal anomaly sensors with 850 hPa trajectory coupling.",

    forecastTitle: "Air Quality Expected to Deteriorate",
    forecastSummary: (current, predicted) => `Prognostic models predict AQI rising from ${current} to ${predicted} over the next few hours.`,
    forecastDesc: "Coupled prognostic atmospheric models forecast a drop in the Planetary Boundary Layer (PBL) mixing height and nocturnal thermal inversion, trapping surface emissions and causing an evening AQI spike.",
    forecastLocation: "Delhi-NCR Airshed (Next 3–6 Hours)",
    forecastAction: "Plan your outdoor commutes and workouts earlier or later when dispersion conditions are more favorable.",
    forecastSensitive: "Ensure indoor air purifiers are activated ahead of the projected evening pollution surge.",
    forecastSourceLabel: "NCR-72 Picard Feedback Model",
    forecastSourceDetail: (predicted, time) => `Aerosol-meteorology radiative forcing simulation predicts peak AQI of ${predicted} at ${time}.`,

    exposureTitle: "Elevated Personal Exposure Risk",
    exposureSummary: "Current ambient particulate density poses rapid cumulative inhalation risk.",
    exposureDesc: (pm25) => `At current PM2.5 levels (${pm25} µg/m³), spending 60 minutes outdoors during active exertion results in an estimated equivalent inhalation of multiple cigarette micro-particulates.`,
    exposureLocation: "Active Ambient Zone",
    exposureAction: "Check your personal daily exposure budget in the Exposure Tracker to optimize transit routes and indoor timing.",
    exposureSensitive: "Avoid any strenuous cardio workouts outdoors.",
    exposureSourceLabel: "Personal Dosimetry & Respiratory Model",
    exposureSourceDetail: "Computed against WHO 24-hour PM2.5 baseline guidelines.",

    histTitle1: "Evening Particulate Surge Resolved",
    histSummary1: "PM2.5 peaked at 168 µg/m³ during peak evening transit rush, now stabilized.",
    histDesc1: "Evening rush hour traffic coupled with declining boundary layer depth caused a temporary surge, which has now settled to baseline levels.",
    histLocation1: "Anand Vihar & East Delhi Corridor",
    histAction1: "Conditions normalized back to daily average.",
    histSensitive1: "Normal precautionary measures apply.",
    histSourceLabel1: "CAAQMS Archived Telemetry",
    histSourceDetail1: "Event resolved and verified by monitoring network.",

    histTitle2: "Nocturnal Inversion Dissipated",
    histSummary2: "Morning solar heating successfully restored vertical mixing layer depth.",
    histDesc2: "Surface temperature inversion layer broke as ground temperature rose past 21°C, allowing trapped ground pollutants to disperse vertically.",
    histLocation2: "Central & South Delhi",
    histAction2: "Vertical mixing restored.",
    histSensitive2: "Standard precautions.",
    histSourceLabel2: "Atmospheric Sounding Profile",
    histSourceDetail2: "Lapse rate returned to positive gradient.",
  },

  hi: {
    severeTitle: "गंभीर वायु गुणवत्ता आपातकालीन चेतावनी",
    severeSummary: (aqi) => `क्षेत्रीय AQI ${aqi} (गंभीर) पर पहुंच गया है। दिल्ली-एनसीआर में वायु प्रदूषण खतरनाक स्तर पर है।`,
    severeDesc: (pm25) => `वायुमंडलीय निगरानी स्टेशनों ने राष्ट्रीय राजधानी क्षेत्र में गंभीर प्रदूषक सांद्रता दर्ज की है। सूक्ष्म कण पदार्थ (PM2.5: ${pm25} µg/m³) वर्तमान में CPCB राष्ट्रीय सुरक्षा सीमा से 8 गुना अधिक है।`,
    severeLocation: "दिल्ली-एनसीआर क्षेत्रीय नेटवर्क (सभी 11 जिले)",
    severeAction: "सभी बाहरी शारीरिक गतिविधियों से बचें। खिड़कियां और दरवाजे कसकर बंद रखें। उपलब्ध हो तो HEPA एयर फिल्टर चलाएं।",
    severeSensitive: "बच्चों, वरिष्ठ नागरिकों और श्वसन/हृदय रोगियों को सख्ती से घर के अंदर रहना चाहिए और निर्धारित दवाइयां पास रखनी चाहिए।",
    severeSourceLabel: "CPCB मल्टी-स्टेशन ग्रिड",
    severeSourceDetail: "43 निरंतर परिवेशी वायु गुणवत्ता निगरानी स्टेशनों द्वारा पुष्टि की गई।",

    veryPoorTitle: "बहुत खराब वायु गुणवत्ता चेतावनी",
    veryPoorSummary: (aqi) => `दिल्ली-एनसीआर में वायु गुणवत्ता बहुत खराब स्तर पर पहुंच गई है (AQI ${aqi})।`,
    veryPoorDesc: (pm25) => `शहरी वायुमंडल में लगातार उच्च कण घनत्व का पता चला है। PM2.5 का स्तर वर्तमान में औसतन ${pm25} µg/m³ है, जो बाहरी गतिविधि के दौरान लंबे समय तक श्वसन असुविधा का कारण बनता है।`,
    veryPoorLocation: "दिल्ली-एनसीआर शहरी महानगरीय क्षेत्र",
    veryPoorAction: "विशेषकर सुबह और शाम के व्यस्त समय में लंबे समय तक बाहरी श्रम कम करें। यात्रा करते समय N95 मास्क पहनें।",
    veryPoorSensitive: "अस्थमा या हृदय रोग वाले व्यक्तियों को बाहरी संपर्क सीमित करना चाहिए।",
    veryPoorSourceLabel: "CPCB / DPCC रीयल-टाइम टेलीमेट्री",
    veryPoorSourceDetail: "बहु-प्रदाता परिवेशी निगरानी नेटवर्क से सत्यापित।",

    poorTitle: "खराब वायु गुणवत्ता सलाह",
    poorSummary: (aqi) => `दिल्ली-एनसीआर में वायु गुणवत्ता खराब श्रेणी (AQI ${aqi}) में है।`,
    poorDesc: (pm25) => `मध्यम-से-खराब प्रसार स्थितियों के कारण सूक्ष्म कणों (PM2.5: ${pm25} µg/m³) का जमाव हो रहा है। बाहरी हवा संवेदनशील समूहों के लिए प्रतिकूल है।`,
    poorLocation: "दिल्ली-एनसीआर महानगरीय क्षेत्र",
    poorAction: "कठिन बाहरी गतिविधियां कम करें। भीड़भाड़ वाली सड़कों पर सुरक्षात्मक मास्क पहनने पर विचार करें।",
    poorSensitive: "संवेदनशील व्यक्तियों को नियमित विश्राम लेना चाहिए और उच्च-यातायात सड़कों से बचना चाहिए।",
    poorSourceLabel: "CAAQMS लाइव टेलीमेट्री",
    poorSourceDetail: "परिवेशी निगरानी नेटवर्क से एकत्रित।",

    hotspotTitle: (name) => `स्थानीय हॉटस्पॉट उछाल: ${name}`,
    hotspotSummary: (name, aqi) => `${name} पर वायु प्रदूषण गंभीर स्तर पर पहुंच गया है (AQI ${aqi})।`,
    hotspotDesc: (name) => `${name} पर निरंतर परिवेशी निगरानी में उच्च कण सांद्रता दर्ज हुई। स्थानीय वायुमंडलीय स्थितियां और आसपास के घने यातायात/औद्योगिक गलियारे ऊर्ध्वाधर प्रसार को सीमित कर रहे हैं।`,
    hotspotAction: "इस माइक्रो-ज़ोन के निवासियों को सुबह और शाम की जॉगिंग से बचना चाहिए और वेंटिलेशन बंद रखना चाहिए।",
    hotspotSensitive: "तीव्र श्वास जलन का उच्च जोखिम। इस क्षेत्र में बाहरी संपर्क से बचें।",
    hotspotSourceLabel: "स्थानीय CAAQMS सेंसर",
    hotspotSourceDetail: (uid) => `स्टेशन UID: ${uid} से सीधा सेंसर फीड।`,

    rapidTitle: "तेजी से प्रदूषण वृद्धि का पता चला",
    rapidSummary: (prev, curr, delta) => `पिछले एक घंटे में PM2.5 में काफी वृद्धि हुई (${prev} → ${curr} µg/m³, +${delta}%)।`,
    rapidDesc: "कम समय में सूक्ष्म कण पदार्थ की तेज आमद दर्ज की गई। तेज वृद्धि आमतौर पर सीमा-परत संपीड़न या स्थानीय भारी यातायात भीड़ को इंगित करती है।",
    rapidLocation: "दिल्ली-एनसीआर केंद्रीय वायु क्षेत्र",
    rapidAction: "बाहरी हवा की गुणवत्ता में अचानक गिरावट की अपेक्षा करें। कण स्तर स्थिर होने तक गैर-जरूरी बाहरी कार्य टालें।",
    rapidSensitive: "कण वृद्धि के दौरान कमजोर व्यक्तियों को बाहरी संपर्क से बचना चाहिए।",
    rapidSourceLabel: "व्युत्पन्न परिवर्तन दर ट्रैकर",
    rapidSourceDetail: (delta) => `PM2.5 वृद्धि दर प्रति घंटा +${delta}% सीमा से अधिक।`,

    industrialTitle: "संभावित औद्योगिक क्षेत्र उत्सर्जन प्रभाव",
    industrialSummary: (name) => `${name} समूह के पास संभावित औद्योगिक उत्सर्जन प्रभाव का पता चला।`,
    industrialDesc: (windDir, windSpd) => `स्थानिक निकटता और स्थानीय पवन प्रक्षेपवक्र (${windDir}, ${windSpd} मी/से) इस औद्योगिक पट्टी में निकटवर्ती विनिर्माण सुविधाओं से संभावित अनुवात कण प्रभाव का संकेत देती है।`,
    industrialAction: "औद्योगिक क्षेत्रों के पास रहने वाले निवासियों को रात और सुबह के समय औद्योगिक गलियारों की ओर वाली खिड़कियां बंद रखनी चाहिए।",
    industrialSensitive: "रासायनिक या गंधकयुक्त गंध के प्रति सावधान रहें। समूह के पास रहने पर कार्बन/HEPA इनडोर फिल्टर का उपयोग करें।",
    industrialSourceLabel: "दिल्ली औद्योगिक समूह रजिस्ट्री (CPCB टियर 1)",
    industrialSourceDetail: (sector) => `क्षेत्र: ${sector}। अनुवात दिशा में स्थानिक सहसंबंध का आकलन।`,

    fireTitle: "अपस्ट्रीम आग और बायोमास धुआं गतिविधि का पता चला",
    fireSummary: (count) => `उपग्रह पहचान ने अपस्ट्रीम कृषि पट्टियों में ${count} सक्रिय थर्मल हॉटस्पॉट की पहचान की।`,
    fireDesc: (frp, state) => `NASA FIRMS VIIRS उपग्रह सेंसरों ने सक्रिय बायोमास जलने के संकेत पाए (पीक FRP: ${frp} MW, ${state} में)। क्षेत्रीय 850 hPa पवन प्रक्षेपवक्र दिल्ली-एनसीआर की ओर संभावित वायुमंडलीय धुएं के प्रवाह का संकेत देते हैं।`,
    fireAction: "देर शाम और भोर में धुंधले आसमान और कम दृश्यता की अपेक्षा करें। सुबह जल्दी बाहरी गतिविधियां सीमित करें।",
    fireSensitive: "धुएं के कणों में महीन कार्बनिक कार्बन होता है। बाहर होने पर कसकर फिट N95 मास्क का उपयोग करें।",
    fireSourceLabel: "NASA FIRMS उपग्रह टेलीमेट्री",
    fireSourceDetail: "VIIRS/MODIS थर्मल विसंगति सेंसरों द्वारा 850 hPa प्रक्षेपवक्र युग्मन के साथ पुष्टि।",

    forecastTitle: "वायु गुणवत्ता में गिरावट की आशंका",
    forecastSummary: (current, predicted) => `पूर्वानुमान मॉडल अगले कुछ घंटों में AQI ${current} से ${predicted} तक बढ़ने की भविष्यवाणी करते हैं।`,
    forecastDesc: "युग्मित वायुमंडलीय मॉडल ग्रहीय सीमा परत (PBL) मिश्रण ऊंचाई में गिरावट और रात्रिकालीन तापीय व्युत्क्रम का पूर्वानुमान लगाते हैं, जो सतही उत्सर्जन को फंसाकर शाम के AQI स्पाइक का कारण बनता है।",
    forecastLocation: "दिल्ली-एनसीआर वायु क्षेत्र (अगले 3-6 घंटे)",
    forecastAction: "अपनी बाहरी यात्राओं और व्यायाम की योजना तब बनाएं जब प्रसार स्थितियां अधिक अनुकूल हों।",
    forecastSensitive: "अनुमानित शाम के प्रदूषण उछाल से पहले इनडोर एयर प्यूरीफायर चालू करें।",
    forecastSourceLabel: "NCR-72 पिकार्ड फीडबैक मॉडल",
    forecastSourceDetail: (predicted, time) => `एरोसोल-मौसम विकिरण बल सिमुलेशन ${time} पर अधिकतम AQI ${predicted} की भविष्यवाणी करता है।`,

    exposureTitle: "व्यक्तिगत जोखिम स्तर में वृद्धि",
    exposureSummary: "वर्तमान परिवेशी कण घनत्व तीव्र संचयी श्वसन जोखिम पैदा करता है।",
    exposureDesc: (pm25) => `वर्तमान PM2.5 स्तर (${pm25} µg/m³) पर, सक्रिय श्रम के दौरान 60 मिनट बाहर बिताने से कई सिगरेट सूक्ष्म कणों के समकक्ष श्वसन अनुमान होता है।`,
    exposureLocation: "सक्रिय परिवेशी क्षेत्र",
    exposureAction: "अपने दैनिक जोखिम बजट की जांच एक्सपोजर ट्रैकर में करें ताकि यात्रा मार्ग और इनडोर समय अनुकूलित हो सके।",
    exposureSensitive: "बाहर कोई भी कठिन कार्डियो व्यायाम से बचें।",
    exposureSourceLabel: "व्यक्तिगत डोसीमेट्री और श्वसन मॉडल",
    exposureSourceDetail: "WHO 24 घंटे PM2.5 बेसलाइन दिशानिर्देशों के विरुद्ध गणना।",

    histTitle1: "शाम का कण उछाल हल हुआ",
    histSummary1: "शाम के व्यस्त यातायात के दौरान PM2.5 168 µg/m³ पर पहुंचा, अब स्थिर हो गया है।",
    histDesc1: "शाम के व्यस्त यातायात और घटती सीमा परत गहराई के कारण अस्थायी उछाल आया, जो अब सामान्य स्तर पर आ गया है।",
    histLocation1: "आनंद विहार और पूर्वी दिल्ली गलियारा",
    histAction1: "स्थितियां दैनिक औसत पर सामान्य हुईं।",
    histSensitive1: "सामान्य एहतियाती उपाय लागू।",
    histSourceLabel1: "CAAQMS संग्रहीत टेलीमेट्री",
    histSourceDetail1: "निगरानी नेटवर्क द्वारा घटना हल और सत्यापित।",

    histTitle2: "रात्रिकालीन व्युत्क्रम समाप्त",
    histSummary2: "सुबह की सौर ऊष्मा ने सफलतापूर्वक ऊर्ध्वाधर मिश्रण परत गहराई बहाल की।",
    histDesc2: "भूमि तापमान 21°C से ऊपर बढ़ने पर सतह तापमान व्युत्क्रम परत टूट गई, जिससे फंसे हुए भूमि प्रदूषक ऊर्ध्वाधर रूप से फैल सके।",
    histLocation2: "मध्य और दक्षिण दिल्ली",
    histAction2: "ऊर्ध्वाधर मिश्रण बहाल हुआ।",
    histSensitive2: "मानक एहतियाती उपाय।",
    histSourceLabel2: "वायुमंडलीय साउंडिंग प्रोफाइल",
    histSourceDetail2: "ह्रास दर सकारात्मक प्रवणता में लौटी।",
  },

  ta: {
    severeTitle: "கடுமையான காற்றுத் தர அவசர எச்சரிக்கை",
    severeSummary: (aqi) => `பிராந்திய AQI ${aqi} (கடுமையான) நிலையை எட்டியுள்ளது. தில்லி-என்சிஆர் முழுவதும் காற்று மாசுபாடு ஆபத்தான நிலையில் உள்ளது.`,
    severeDesc: (pm25) => `வளிமண்டல கண்காணிப்பு நிலையங்கள் தேசிய தலைநகர் பகுதி முழுவதும் கடுமையான மாசுபடுத்தி செறிவைக் காட்டுகின்றன. நுண்ணிய துகள் பொருள் (PM2.5: ${pm25} µg/m³) தற்போது CPCB தேசிய பாதுகாப்பு வரம்பை விட 8 மடங்கு அதிகமாக உள்ளது.`,
    severeLocation: "தில்லி-என்சிஆர் பிராந்திய வலையமைப்பு (அனைத்து 11 மாவட்டங்கள்)",
    severeAction: "அனைத்து வெளிப்புற உடல் செயல்பாடுகளையும் தவிர்க்கவும். ஜன்னல்கள் மற்றும் கதவுகளை இறுக்கமாக மூடி வைக்கவும். கிடைத்தால் HEPA காற்று வடிகட்டியை இயக்கவும்.",
    severeSensitive: "குழந்தைகள், மூத்த குடிமக்கள் மற்றும் சுவாச/இதய நோயாளிகள் கண்டிப்பாக வீட்டுக்குள் இருக்க வேண்டும்.",
    severeSourceLabel: "CPCB பல-நிலைய கட்டம்",
    severeSourceDetail: "43 தொடர்ச்சியான சுற்றுச்சூழல் காற்றுத் தர கண்காணிப்பு நிலையங்களால் உறுதிப்படுத்தப்பட்டது.",

    veryPoorTitle: "மிகவும் மோசமான காற்றுத் தர எச்சரிக்கை",
    veryPoorSummary: (aqi) => `தில்லி-என்சிஆரில் காற்றுத் தரம் மிகவும் மோசமான நிலையை எட்டியுள்ளது (AQI ${aqi}).`,
    veryPoorDesc: (pm25) => `நகர்ப்புற வளிமண்டலத்தில் தொடர்ச்சியான அதிக துகள் அடர்த்தி கண்டறியப்பட்டது. PM2.5 அளவுகள் தற்போது சராசரியாக ${pm25} µg/m³ ஆக உள்ளன.`,
    veryPoorLocation: "தில்லி-என்சிஆர் நகர்ப்புற பெருநகரப் பகுதி",
    veryPoorAction: "குறிப்பாக காலை மற்றும் மாலை நெரிசல் நேரங்களில் நீண்ட நேர வெளிப்புற உழைப்பைக் குறைக்கவும். பயணிக்கும்போது N95 முகக்கவசம் அணியவும்.",
    veryPoorSensitive: "ஆஸ்துமா அல்லது இதய நோய் உள்ளவர்கள் வெளிப்புற தொடர்பைக் கட்டுப்படுத்த வேண்டும்.",
    veryPoorSourceLabel: "CPCB / DPCC நிகழ்நேர தொலைமானி",
    veryPoorSourceDetail: "பல-வழங்குனர் சுற்றுச்சூழல் கண்காணிப்பு வலையமைப்புடன் சரிபார்க்கப்பட்டது.",

    poorTitle: "மோசமான காற்றுத் தர ஆலோசனை",
    poorSummary: (aqi) => `தில்லி-என்சிஆரில் காற்றுத் தரம் மோசமான வகையில் உள்ளது (AQI ${aqi}).`,
    poorDesc: (pm25) => `மிதமான-முதல்-மோசமான பரவல் நிலைமைகள் நுண்ணிய துகள்கள் (PM2.5: ${pm25} µg/m³) குவிவதற்கு காரணமாகின்றன. வெளிப்புற காற்று உணர்திறன் குழுக்களுக்கு பாதகமானது.`,
    poorLocation: "தில்லி-என்சிஆர் பெருநகரப் பகுதி",
    poorAction: "கடினமான வெளிப்புற செயல்பாடுகளைக் குறைக்கவும். நெரிசலான சாலைகளில் பாதுகாப்பு முகக்கவசம் அணிய பரிசீலிக்கவும்.",
    poorSensitive: "உணர்திறன் நபர்கள் வழக்கமான இடைவேளைகள் எடுக்க வேண்டும்.",
    poorSourceLabel: "CAAQMS நேரடி தொலைமானி",
    poorSourceDetail: "சுற்றுச்சூழல் கண்காணிப்பு வலையமைப்பு முழுவதும் திரட்டப்பட்டது.",

    hotspotTitle: (name) => `உள்ளூர் ஹாட்ஸ்பாட் எழுச்சி: ${name}`,
    hotspotSummary: (name, aqi) => `${name} இல் காற்று மாசுபாடு தீவிர நிலையை எட்டியுள்ளது (AQI ${aqi}).`,
    hotspotDesc: (name) => `${name} இல் தொடர்ச்சியான சுற்றுச்சூழல் கண்காணிப்பில் அதிக துகள் செறிவு பதிவாகியுள்ளது.`,
    hotspotAction: "இந்த நுண்-மண்டலத்தில் உள்ள குடியிருப்பாளர்கள் காலை-மாலை நடை பயிற்சியைத் தவிர்க்க வேண்டும்.",
    hotspotSensitive: "கடுமையான சுவாச எரிச்சலின் அதிக ஆபத்து. இந்த பகுதியில் வெளிப்புற தொடர்பைத் தவிர்க்கவும்.",
    hotspotSourceLabel: "உள்ளூர் CAAQMS உணரி",
    hotspotSourceDetail: (uid) => `நிலையம் UID: ${uid} இலிருந்து நேரடி உணரி ஊட்டம்.`,

    rapidTitle: "விரைவான மாசுபாடு எழுச்சி கண்டறியப்பட்டது",
    rapidSummary: (prev, curr, delta) => `கடந்த ஒரு மணி நேரத்தில் PM2.5 கணிசமாக அதிகரித்தது (${prev} → ${curr} µg/m³, +${delta}%).`,
    rapidDesc: "குறுகிய நேரத்தில் நுண்ணிய துகள் பொருளின் விரைவான வருகை பதிவாகியுள்ளது.",
    rapidLocation: "தில்லி-என்சிஆர் மைய வளிமண்டலம்",
    rapidAction: "வெளிப்புற காற்று தெளிவில் திடீர் சரிவை எதிர்பாருங்கள். துகள் அளவுகள் நிலைப்படும் வரை அத்தியாவசியமற்ற வெளிப்புற வேலைகளை ஒத்திவையுங்கள்.",
    rapidSensitive: "துகள் எழுச்சி நடக்கும்போது பாதிக்கப்படக்கூடிய நபர்கள் வெளிப்புற தொடர்பைத் தவிர்க்க வேண்டும்.",
    rapidSourceLabel: "மாற்ற விகித கண்காணிப்பான்",
    rapidSourceDetail: (delta) => `PM2.5 அதிகரிப்பு விகிதம் மணிக்கு +${delta}% வரம்பை மீறியது.`,

    industrialTitle: "சாத்தியமான தொழிற்சாலை மண்டல உமிழ்வு தாக்கம்",
    industrialSummary: (name) => `${name} தொகுப்பருகே சாத்தியமான தொழிற்சாலை உமிழ்வு தாக்கம் கண்டறியப்பட்டது.`,
    industrialDesc: (windDir, windSpd) => `இடஞ்சார் அருகாமை மற்றும் உள்ளூர் காற்றின் பாதை (${windDir}, ${windSpd} மீ/வி) அருகிலுள்ள உற்பத்தி வசதிகளிலிருந்து சாத்தியமான துகள் தாக்கத்தைக் குறிக்கிறது.`,
    industrialAction: "தொழிற்சாலை பகுதிகளுக்கு அருகில் வசிப்பவர்கள் இரவு மற்றும் அதிகாலை நேரங்களில் ஜன்னல்களை மூடி வைக்க வேண்டும்.",
    industrialSensitive: "வேதியியல் அல்லது கந்தக வாசனைகள் குறித்து எச்சரிக்கையாக இருங்கள்.",
    industrialSourceLabel: "தில்லி தொழிற்சாலை பதிவேடு (CPCB அடுக்கு 1)",
    industrialSourceDetail: (sector) => `பிரிவு: ${sector}. கீழ்நோக்கிய காற்றின் திசையில் இடஞ்சார்ந்த தொடர்பு மதிப்பிடப்பட்டது.`,

    fireTitle: "மேல்நிலை தீ மற்றும் உயிரி புகை செயல்பாடு கண்டறியப்பட்டது",
    fireSummary: (count) => `செயற்கைக்கோள் கண்டறிதல் மேல்நிலை விவசாய பகுதிகளில் ${count} செயலில் உள்ள வெப்ப புள்ளிகளை அடையாளம் கண்டுள்ளது.`,
    fireDesc: (frp, state) => `NASA FIRMS VIIRS செயற்கைக்கோள் உணரிகள் செயலில் உள்ள உயிரி எரிப்பு அடையாளங்களைக் கண்டறிந்தன (உச்ச FRP: ${frp} MW, ${state}).`,
    fireAction: "மாலை மற்றும் விடியலில் மூடுபனி வானம் எதிர்பாருங்கள். அதிகாலை வெளிப்புற செயல்பாடுகளை கட்டுப்படுத்துங்கள்.",
    fireSensitive: "புகை துகள்களில் நுண்ணிய கரிமக் கார்பன் உள்ளது. வெளியே இருந்தால் N95 முகக்கவசம் பயன்படுத்துங்கள்.",
    fireSourceLabel: "NASA FIRMS செயற்கைக்கோள் தொலைமானி",
    fireSourceDetail: "VIIRS/MODIS வெப்ப ஒழுங்கின்மை உணரிகளால் உறுதிப்படுத்தப்பட்டது.",

    forecastTitle: "காற்றுத் தரம் மோசமடையும் என எதிர்பார்க்கப்படுகிறது",
    forecastSummary: (current, predicted) => `முன்னறிவிப்பு மாதிரிகள் அடுத்த சில மணி நேரங்களில் AQI ${current} இலிருந்து ${predicted} ஆக உயரும் என கணிக்கின்றன.`,
    forecastDesc: "இணைந்த வளிமண்டல மாதிரிகள் கிரக எல்லை அடுக்கு கலப்பு உயரத்தில் வீழ்ச்சி மற்றும் இரவு வெப்ப தலைகீழ்மாற்றத்தை முன்னறிவிக்கின்றன.",
    forecastLocation: "தில்லி-என்சிஆர் வளிமண்டலம் (அடுத்த 3-6 மணி நேரம்)",
    forecastAction: "பரவல் நிலைமைகள் சாதகமாக இருக்கும்போது வெளிப்புற பயணங்கள் மற்றும் உடற்பயிற்சிகளைத் திட்டமிடுங்கள்.",
    forecastSensitive: "கணிக்கப்பட்ட மாலை மாசுபாடு எழுச்சிக்கு முன் உள்ளக காற்று சுத்திகரிப்பிகளை இயக்குங்கள்.",
    forecastSourceLabel: "NCR-72 பிக்கார்ட் பின்னூட்ட மாதிரி",
    forecastSourceDetail: (predicted, time) => `ஏரோசால்-வானிலை கதிர்வீச்சு சிமுலேஷன் ${time} இல் உச்ச AQI ${predicted} ஐ கணிக்கிறது.`,

    exposureTitle: "உயர்ந்த தனிநபர் வெளிப்பாட்டு ஆபத்து",
    exposureSummary: "தற்போதைய சுற்றுச்சூழல் துகள் அடர்த்தி விரைவான திரட்சி சுவாச ஆபத்தை ஏற்படுத்துகிறது.",
    exposureDesc: (pm25) => `தற்போதைய PM2.5 அளவுகளில் (${pm25} µg/m³), செயலில் உழைப்பின் போது 60 நிமிடங்கள் வெளியில் செலவிடுவது பல சிகரெட் நுண்துகள்களுக்கு சமமான சுவாசத்தை ஏற்படுத்துகிறது.`,
    exposureLocation: "செயலில் உள்ள சுற்றுச்சூழல் மண்டலம்",
    exposureAction: "போக்குவரத்து வழிகள் மற்றும் உள்ளக நேரத்தை மேம்படுத்த வெளிப்பாடு கண்காணிப்பியில் உங்கள் தினசரி வெளிப்பாட்டு வரவு-செலவுத் திட்டத்தை சரிபார்க்கவும்.",
    exposureSensitive: "வெளியில் எந்த கடினமான கார்டியோ பயிற்சிகளையும் தவிர்க்கவும்.",
    exposureSourceLabel: "தனிநபர் அளவீட்டு மற்றும் சுவாச மாதிரி",
    exposureSourceDetail: "WHO 24 மணி நேர PM2.5 அடிப்படை வழிகாட்டுதல்களுக்கு எதிராக கணக்கிடப்பட்டது.",

    histTitle1: "மாலை துகள் எழுச்சி தீர்க்கப்பட்டது",
    histSummary1: "மாலை நெரிசல் நேரத்தில் PM2.5 168 µg/m³ ஐ எட்டியது, இப்போது நிலைப்படுத்தப்பட்டது.",
    histDesc1: "மாலை நெரிசல் போக்குவரத்தும் குறையும் எல்லை அடுக்கு ஆழமும் தற்காலிக எழுச்சிக்கு காரணமாக இருந்தன.",
    histLocation1: "ஆனந்த் விகார் மற்றும் கிழக்கு தில்லி பாதை",
    histAction1: "நிலைமைகள் தினசரி சராசரிக்கு சீரானது.",
    histSensitive1: "சாதாரண முன்னெச்சரிக்கை நடவடிக்கைகள் பொருந்தும்.",
    histSourceLabel1: "CAAQMS காப்பகப்படுத்தப்பட்ட தொலைமானி",
    histSourceDetail1: "கண்காணிப்பு வலையமைப்பால் நிகழ்வு தீர்க்கப்பட்டு சரிபார்க்கப்பட்டது.",

    histTitle2: "இரவு நேர தலைகீழ்மாற்றம் கலைந்தது",
    histSummary2: "காலை சூரிய வெப்பம் செங்குத்து கலப்பு அடுக்கு ஆழத்தை வெற்றிகரமாக மீட்டது.",
    histDesc2: "நில வெப்பநிலை 21°C ஐ தாண்டியதும் மேற்பரப்பு வெப்பநிலை தலைகீழ்மாற்ற அடுக்கு உடைந்தது.",
    histLocation2: "மத்திய மற்றும் தெற்கு தில்லி",
    histAction2: "செங்குத்து கலப்பு மீட்கப்பட்டது.",
    histSensitive2: "நிலையான முன்னெச்சரிக்கைகள்.",
    histSourceLabel2: "வளிமண்டல ஒலி சுயவிவரம்",
    histSourceDetail2: "சரிவு விகிதம் நேர்மறை சாய்வுக்குத் திரும்பியது.",
  },
};
