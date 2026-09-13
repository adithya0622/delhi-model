export default async function handler(req, res) {
  // Support CORS
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  const { text, lang } = req.query;
  const langCode = lang === "ta" ? "ta" : lang === "hi" ? "hi" : "en";
  const cleanText = (text || "").trim().slice(0, 200);

  if (!cleanText) {
    return res.status(400).json({ error: "Missing text parameter" });
  }

  const googleTtsUrl = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encodeURIComponent(
    cleanText
  )}&tl=${langCode}&client=tw-ob`;

  try {
    const upstreamRes = await fetch(googleTtsUrl, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        Referer: "https://translate.google.com/",
      },
    });

    if (!upstreamRes.ok) {
      return res.status(upstreamRes.status).json({ error: "Upstream TTS service error" });
    }

    const arrayBuffer = await upstreamRes.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);

    res.setHeader("Content-Type", "audio/mpeg");
    res.setHeader("Cache-Control", "public, max-age=86400, s-maxage=86400");
    return res.status(200).send(buffer);
  } catch (err) {
    console.error("[TTS Serverless Error]:", err);
    return res.status(500).json({ error: err.message || "Failed to generate speech audio" });
  }
}
