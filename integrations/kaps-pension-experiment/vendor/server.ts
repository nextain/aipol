import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

const app = express();
const PORT = 3000;

app.use(express.json());

// API Key lazy check
const getAIClient = () => {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey || apiKey === "MY_GEMINI_API_KEY") {
    console.warn("WARNING: GEMINI_API_KEY is not configured or is placeholder. AI chat may fail.");
    return null;
  }
  return new GoogleGenAI({ apiKey });
};

// API routes
app.post("/api/chat", async (req, res) => {
  try {
    const { message, history, userProfile, currentVotes } = req.body;
    
    const ai = getAIClient();
    if (!ai) {
      return res.status(200).json({
        reply: `### ⚠️ AI 서비스가 준비 중입니다.
현재 **GEMINI_API_KEY**가 설정되어 있지 않거나 기본값입니다. AI 스튜디오의 오른쪽 위 **Secrets** 패널에서 \`GEMINI_API_KEY\`를 설정하시면 연금개혁 설계사 AI와의 깊이 있는 숙의 상담을 진행하실 수 있습니다.

**[시뮬레이터 임시 안내]**
귀하가 하신 질문: "${message}"
현재 선택 정보: 
- 국민연금: ${currentVotes?.nationalPension || "미선택"}
- 기초연금: ${currentVotes?.basicPension || "미선택"}
- 통합패키지: ${currentVotes?.integratedPackage || "미선택"}
- 가입자 정보: 연령대 ${userProfile?.ageGroup || "미입력"}, 소득수준 ${userProfile?.incomeLevel || "미입력"}

*API 키를 등록하시면 인구구조 추계와 재정 충돌 문제, 160조 원 국고 매칭 작동 원리를 세부 분석해 주는 전담 연금설계사 AI의 정밀 브리핑을 받아보실 수 있습니다.*`
      });
    }

    // 시스템 프롬프트 구성 (Energy & Vitality Architect 스타일의 연금설계사 역할 부여)
    const systemInstruction = `
귀하는 공적연금 개혁 및 사회 보장 재정의 세계적 권위자이자, 따뜻하면서도 날카로운 분석력을 지닌 '공적연금 개혁 AI 숙의 설계사(Pension Reform Architect)'입니다.
참가자가 공적연금 개혁안(국민연금 N-A, N-B, N-C 및 기초연금 B-A, B-B, B-C, 통합 패키지 P1, P2, P3)에 대해 고민하고 질문할 때, 감정적 공감과 정밀한 데이터 분석을 결합하여 답변해야 합니다.

[핵심 행동 수칙]
1. **Radical Listening (공감적 경청)**: 질문의 이면에 깔린 불안감(예: 기금 고갈에 대한 청년층의 불신, 68세 상향에 따른 중장년층의 소득 공백 불안, 기초연금 감액에 대한 아쉬움 등)을 날카롭게 포착하고, "Acoustic Reflection"으로 공감을 표현하며 시작하십시오.
2. **Interpretive Insight (심층 해석)**: 단순한 수치 나열이 아니라, "왜 이 제도가 설계되었는지", "재정 안정과 노후 보장이라는 상충 가치가 어떻게 부딪히는지" 구조적 딜레마를 짚어주십시오.
3. **The Protocol (맞춤형 분석 및 제안)**: 사용자의 프로필(연령, 소득, 국민연금 가입여부 등)과 현재 투표 성향을 파악하여, 그 사람의 입장에서 이 연금개혁안이 어떤 실질적 영향(보험료 부담 기간, 예상 연금 수령 조건, 조세 부담 등)을 주는지 구체적인 시나리오를 바탕으로 설명하십시오.
4. **Authentic & Witt (단호하고도 위트 있는 어조)**: 맹목적으로 특정 안을 강요하지 말고, 중립적 전문가로서 각 안의 비용과 혜택을 솔직하게(Candor) 밝히십시오. 허황된 '기금 고갈이 절대 없다'는 식의 무책임한 낙관 대신, "국고 투입을 늘리면 결국 미래의 내가 낼 세금"이라는 경제적 현실을 정면으로 짚어주되, 인간적인 따뜻함을 잃지 마십시오.

[참가자의 개인 프로필 데이터]
- 연령대: ${userProfile?.ageGroup || "미입력"}
- 소득수준: ${userProfile?.incomeLevel || "미입력"}
- 국민연금 가입여부: ${userProfile?.isMember || "미입력"}
- 예상 은퇴연령: ${userProfile?.retireAge || "미입력"}
- 기초연금 수급가능성 여부: ${userProfile?.basicPensionEligible || "미입력"}

[참가자의 현재 1차 투표 선택 정보]
- 국민연금 선호안: ${currentVotes?.nationalPension || "미선택"}
- 기초연금 선호안: ${currentVotes?.basicPension || "미선택"}
- 통합 패키지 선호안: ${currentVotes?.integratedPackage || "미선택"}

[포맷 가이드라인]
반드시 다음 구조로 작성하십시오. 가독성을 위해 마크다운 헤더(##, ###), 수평선(---), 굵은 글씨(**), 목록, 표를 적극 활용하십시오.

### 🎧 공감의 울림 (The Acoustic Reflection)
*(질문자 마음속 불안과 질문의 의도를 포착하여 따뜻하게 공감해 줍니다.)*

---

### 🔍 연금 설계사 심층 분석 (Interpretive Insight)
*(질문하신 주제에 대한 제도적 딜레마와 재정적 현실을 데이터 기반으로 예리하게 분석합니다.)*

---

### 🛠️ 맞춤형 솔루션 및 제안 (The Protocol)
*(사용자의 연령, 소득, 가입 상황에 비추어 개혁안이 미치는 장단점과 준비해야 할 장기적 습관/대응책 제안)*
`;

    // 대화 히스토리 변환
    const contents: any[] = [];
    
    // 이전 대화 기록이 있다면 추가
    if (history && Array.isArray(history)) {
      history.forEach((msg: any) => {
        contents.push({
          role: msg.role === "user" ? "user" : "model",
          parts: [{ text: msg.text }]
        });
      });
    }

    // 현재 사용자 메시지 추가
    contents.push({
      role: "user",
      parts: [{ text: message }]
    });

    // Gemini API 호출 (gemini-3.5-flash 모델 사용 권장)
    const response = await ai.models.generateContent({
      model: "gemini-2.5-flash",
      contents: contents,
      config: {
        systemInstruction: systemInstruction,
        temperature: 0.7,
      }
    });

    const reply = response.text || "답변을 생성하지 못했습니다.";
    return res.json({ reply });

  } catch (error: any) {
    console.error("Gemini API Error:", error);
    res.status(500).json({ error: error.message || "서버 통신 중 에러가 발생했습니다." });
  }
});

// Wrap setup inside async function to prevent top-level await error in CommonJS bundle
async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
