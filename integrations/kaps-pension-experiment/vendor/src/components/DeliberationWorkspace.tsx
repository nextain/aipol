import React, { useState, useRef, useEffect } from "react";
import { UserProfile, VoteData, ChatMessage } from "../types";
import {
  Send,
  Sparkles,
  AlertTriangle,
  ArrowRight,
  Info,
  Scale,
  Check,
  RefreshCw,
  User,
  DollarSign,
  Calendar,
  Shield,
  TrendingDown,
} from "lucide-react";
import ReactMarkdown from "react-markdown";

interface DeliberationWorkspaceProps {
  profile: UserProfile;
  votes: VoteData;
  setVotes: (votes: VoteData) => void;
  onNext: () => void;
}

export default function DeliberationWorkspace({
  profile,
  votes,
  setVotes,
  onNext,
}: DeliberationWorkspaceProps) {
  // --- Part 1: AI Chat state ---
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "model",
      text: `### 🎙️ 안녕하세요! 실시간 AI 연금 대기실에 오신 것을 환영합니다.
저는 귀하의 토론과 시뮬레이션을 도울 전문 수석 설계사 **AI 연금 도우미**입니다.

입력하신 나이, 가구 소득수준, 은퇴 예정일 및 1차 투표 결과를 파악하여 전용 맞춤 대화를 나눌 준비가 완료되었습니다.
- **내 연령대**: ${profile.ageGroup || "미입력"}
- **나의 1차 투표 계획**: ${
        votes.integratedPackage === "P1"
          ? "P1 (나이유지·모두균등)"
          : votes.integratedPackage === "P2"
          ? "P2 (나이연장·소득차등)"
          : votes.integratedPackage === "P3"
          ? "P3 (나이연장·저축준비)"
          : "아직 판단 중"
      }

연금 지급 나이를 68세로 미루는 부담, 초반 세금 저축(160조 원)으로 다가올 이웃들의 세부 갈등, 해외 투자 실패 리스크 등 다양한 의문에 관해 질문해 주세요. 정교하게 답변해 드리겠습니다.`,
      timestamp: new Date(),
    },
  ]);
  const [inputText, setInputText] = useState("");
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // --- Part 2: Agreement Checklist state ---
  const [delibQ1, setDelibQ1] = useState<string>("");
  const [delibQ2, setDelibQ2] = useState<string>("");
  const [delibQ3, setDelibQ3] = useState<string>("");
  const [delibQ4, setDelibQ4] = useState<string>("");

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // --- Part 3: Dynamic Profile Impact Logic ---
  const getAgeContext = () => {
    switch (profile.ageGroup) {
      case "20-29":
        return {
          title: "청년 세대 (20대)",
          burden: "보험료가 월급의 13%로 인상될 시, 은퇴 직전까지 최소 35년 이상 무거운 부담을 견뎌내야 합니다. 연금 기금 안전망 신뢰에 민감한 핵심 세대입니다.",
          payoff: "개혁이 타결될 시 기금 소진 시점이 2096년 이후로 연장되어, 내가 은퇴했을 때 연금을 떼이지 않고 고스란히 돌려받는 최고 수준의 안심을 획득합니다.",
          suggestion: "선제적인 100조/60조 저축이 부진하거나 고수익 자산 운용이 정체될 시, 먼 미래에 폭발하는 조세 청구서를 홀로 뒤집어써야 할 우려가 공존합니다.",
        };
      case "30-39":
        return {
          title: "청장년 세대 (30대)",
          burden: "한창 가정을 꾸리고 일하며 커리어를 쌓는 경제 활성기에 월급의 9% → 13% 인상을 맞닥뜨려 매달 생활비 실감 타격이 큰 세대입니다.",
          payoff: "기존 2065년 고갈 예정 년도에 본인이 은퇴기 핵심 나이(60~70대)에 다다르기 때문에, 이 개혁의 성패에 인생 노후의 생존선이 직결되어 있습니다.",
          suggestion: "초기 국고 저축 및 적립 장치(B-C)를 마련해 세수 구멍을 예방하지 않으면, 퇴직 시기에 국가 세금 부담 폭증으로 제도가 무너질 수 있습니다.",
        };
      case "40-49":
        return {
          title: "경제 중추 허리 세대 (40대)",
          burden: "은퇴까지 약 15~25년 남았지만, 교육비·부동산 주거비 부담이 인생 최대치에 이르는 가구 허리층이라 늘어나는 보험료율 부담 체감이 큽니다.",
          payoff: "노후 연금 대체 보장 비율(소득대체율)이 기존 40%에서 43%로 증액 고정되어, 기금의 지속성과 더불어 수령 보장성이 두터워집니다.",
          suggestion: "연금 개시 연령이 만 68세로 늦춰질 경우(N-B, N-C 안), 60세 정년 퇴직 시점과 수령 시점 사이 무려 8년 동안의 소득 단절 '크레바스' 대책이 시급합니다.",
        };
      case "50-59":
        return {
          title: "은퇴 직전 세대 (50대)",
          burden: "국민연금을 낼 기간이 10년 이내로 짧아, 요율 인상에 따른 평생 누적 세금 부담 피해는 젊은 세대에 비해 아주 극소한 편입니다.",
          payoff: "보험료 인상 타격은 피하면서, 43%로 인상된 대체 보장률 수혜를 가깝고 탄탄하게 바로 누리는 세대 안정 구도의 최고 수혜자입니다.",
          suggestion: "출생 연도에 따라 만 65~68세로 연금 타기 시작하는 시기가 미세 조정되므로 개별 수령 타임라인을 사전 점검하고 가구 자산을 배분해 두어야 합니다.",
        };
      case "60-69":
      case "70+":
        return {
          title: "실 수급층 및 고령 세대",
          burden: "연금 보험료 납부 의무는 이미 종료되었거나 사실상 끝나, 보험료율 인상에 의한 소득 마이너스 충격은 완전히 면제된 안심 지대입니다.",
          payoff: "국민연금 수입은 안전히 굳힙니다. 단, 기초연금 분배 방식(B-A, B-B, B-C) 채택 여하에 따라 매달 지갑에 들어오는 추가 연금액이 달라집니다.",
          suggestion: "형편이 어려운 이웃들을 위해 기초연금을 차등 분배하면(B-B, B-C 안), 자산 분위에 따라 내 기초연금액이 깎일 수 있으므로 이해 득실이 엇갈립니다.",
        };
      default:
        return {
          title: "가입인 세대",
          burden: "보험료가 소득의 13%로 인상되면 가구의 실수령 가처분 소득이 소폭 줄어들어 일정 수준의 적응 기간이 필요할 수 있습니다.",
          payoff: "국가 재정 수혈과 자산 불리기로 연금 저금통 고갈 시점을 원천 방어하여, 은퇴 시 연금을 못 받을 것이라는 불확실성을 확실하게 차단합니다.",
          suggestion: "퇴직 시점과 연금 수령 시작 연도 사이의 빈틈, 그리고 내가 탈 기초연금액 차등 비율을 꼼꼼히 확인하십시오.",
        };
    }
  };

  const ageData = getAgeContext();

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim() || loading) return;

    const userMsg: ChatMessage = {
      id: Math.random().toString(),
      role: "user",
      text: inputText,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputText("");
    setLoading(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMsg.text,
          history: messages.slice(1).map((m) => ({ role: m.role, text: m.text })),
          userProfile: profile,
          currentVotes: votes,
        }),
      });

      const data = await response.json();
      if (data.reply) {
        setMessages((prev) => [
          ...prev,
          {
            id: Math.random().toString(),
            role: "model",
            text: data.reply,
            timestamp: new Date(),
          },
        ]);
      } else {
        throw new Error("API Return value failed");
      }
    } catch (err) {
      console.error(err);
      setMessages((prev) => [
        ...prev,
        {
          id: Math.random().toString(),
          role: "model",
          text: `### ⚠️ AI 통신 에러가 일어났습니다.
기본 API 환경변수(\`GEMINI_API_KEY\`)가 비어 있는 경우이거나 일시적 연결 지연입니다. AI 스튜디오 오른쪽 위 Secrets 패널에서 등록 여부를 살펴보실 수 있습니다.

**[연금 전문가 임시 상담 가이드]**
- **수령 개시 나이 68세 완화 대책**: 소득 단절 기간에는 소액 재취업이나 개인연금(IRP) 가교 연금을 확보하는 것이 필수입니다.
- **160조 원 국고 매칭 작동**: 국민연금 초반 100조, 기초연금 60조는 미래 자녀의 조세 폭탄을 방어하기 위한 선제 금융 비축금이나 당장의 재정에 여유가 없다면 연단위 상환 조율이 권장됩니다.`,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const checkValidation = () => {
    return delibQ1 !== "" && delibQ2 !== "" && delibQ3 !== "" && delibQ4 !== "";
  };

  const handleNextStep = () => {
    setVotes({
      ...votes,
      conflictResolution: delibQ2, // Bind Q2 resolution as conflicts answer
    });
    onNext();
  };

  const q1Options = [
    { value: "65", label: "만 65세 수령 나이 유지 (현행 유지)", desc: "정년퇴직 후 소득 공백기 걱정을 없앰. 다만 후대 자녀의 평생 세금 증가 인정." },
    { value: "66", label: "만 66세 수령 나이 (1년 완화 타협안)", desc: "나이 상향의 충격을 소폭 줄이며 가볍게 조절하는 중간 타협." },
    { value: "68", label: "만 68세로 수령 연기 (N-B / N-C 안)", desc: "기금의 장기 재정을 탄탄하게 보존하기 위해 은퇴 상향과 수령 조절 동참." },
  ];

  const q2Options = [
    { value: "NP-100", label: "국민연금 선제 저축에 100조 몰아주기", desc: "기초연금 저축은 잠시 생략, 국민연금 100조 초반 저축을 확실히 달성." },
    { value: "NP-50_BP-50", label: "공평하게 두 연금에 50조 원씩 절반 분할", desc: "국민연금 50조, 기초연금 50조 선제 저축하여 고른 균형 달성." },
    { value: "NP-40_BP-60", label: "기초연금 기금 60조 완수 우선 (청년 세수 차단)", desc: "기초연금 기금 저축 60조를 먼저 모으고, 국민연금은 40조로 긴축 저축." },
    { value: "NO-FUND", label: "초반 저축 없이 매년 세금으로 꼬박 납부", desc: "국채 발생이나 초기 부담을 회피하고 매년 발생하는 돈을 그때그때 세금으로 충당." },
  ];

  return (
    <div className="space-y-6 animate-fade-in" id="deliberation-workspace-master">
      
      {/* 상단 개인 프로필 간이 대시보드 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-5 bg-white rounded-2xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 font-bold text-xs shrink-0">
            <User className="w-4 h-4" />
          </div>
          <div>
            <p className="text-[10px] text-slate-450 font-bold uppercase">내 나이 세대</p>
            <p className="text-xs font-extrabold text-slate-800">{ageData.title}</p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 font-bold text-xs shrink-0">
            <DollarSign className="w-4 h-4" />
          </div>
          <div>
            <p className="text-[10px] text-slate-450 font-bold uppercase">월 가구소득</p>
            <p className="text-xs font-extrabold text-slate-800">
              {profile.incomeLevel === "under_2m" && "200만 미만"}
              {profile.incomeLevel === "2m_4m" && "200만 ~ 400만"}
              {profile.incomeLevel === "4m_6m" && "400만 ~ 600만"}
              {profile.incomeLevel === "6m_8m" && "600만 ~ 800만"}
              {profile.incomeLevel === "over_8m" && "800만 이상"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 font-bold text-xs shrink-0">
            <Calendar className="w-4 h-4" />
          </div>
          <div>
            <p className="text-[10px] text-slate-450 font-bold uppercase">퇴직 예정일</p>
            <p className="text-xs font-extrabold text-slate-800">만 {profile.retireAge}세 은퇴</p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 font-bold text-xs shrink-0">
            <Shield className="w-4 h-4" />
          </div>
          <div>
            <p className="text-[10px] text-slate-450 font-bold uppercase">1차 투표 패키지</p>
            <p className="text-xs font-extrabold text-slate-800">
              {votes.integratedPackage === "P1" && "P1 (나이유지·균등)"}
              {votes.integratedPackage === "P2" && "P2 (나이연장·차등)"}
              {votes.integratedPackage === "P3" && "P3 (나이연장·저축)"}
              {votes.integratedPackage === "NONE" && "마음에 안 듬"}
              {votes.integratedPackage === "UNDECIDED" && "판단 보류"}
            </p>
          </div>
        </div>
      </div>

      {/* 메인 2열 그리드: 왼쪽 AI 리포트 (40%), 오른쪽 AI 챗봇 및 합의 기록지 (60%) */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        
        {/* 왼쪽: 내 노후 AI 맞춤 진단 보고서 */}
        <div className="xl:col-span-5 space-y-5">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="bg-slate-900 text-white p-5">
              <span className="text-[9px] font-extrabold tracking-wider bg-blue-600 px-2 py-0.5 rounded-full uppercase">
                AI BLUEPRINT
              </span>
              <h3 className="text-base font-extrabold text-white mt-1.5">
                내 프로필 기반 AI 맞춤 연금 보고서
              </h3>
            </div>

            <div className="p-5 space-y-4">
              {/* 타임라인 및 영향 A */}
              <div className="p-4 bg-slate-50/80 rounded-xl border border-slate-200 space-y-2">
                <p className="text-xs font-extrabold text-slate-800 flex items-center gap-1">
                  <span className="w-1.5 h-3 bg-blue-600 rounded"></span>
                  1. 생애 보험료 부담 vs 수혜 타임라인
                </p>
                <p className="text-[11px] text-slate-650 leading-relaxed font-medium">
                  <strong>평생 누적 부담:</strong> {ageData.burden}
                </p>
                <p className="text-[11px] text-slate-650 leading-relaxed font-medium pt-1.5 border-t border-slate-200/60">
                  <strong>예상 수령 신뢰도:</strong> {ageData.payoff}
                </p>
              </div>

              {/* 소득 공백 위험 B */}
              <div className="p-4 bg-amber-50/40 rounded-xl border border-amber-100 space-y-2">
                <p className="text-xs font-extrabold text-amber-900 flex items-center gap-1">
                  <span className="w-1.5 h-3 bg-amber-500 rounded"></span>
                  2. 퇴직 나이 대비 소득 공백기 계산
                </p>
                <p className="text-[11px] text-slate-700 leading-relaxed">
                  귀하의 정년 퇴직 희망 연도는 <strong>만 {profile.retireAge}세</strong>입니다. 수령 연령이 만 68세로 늦춰질 경우:
                </p>
                {profile.retireAge < 68 ? (
                  <p className="text-xs text-rose-800 font-extrabold bg-rose-50/50 p-2.5 rounded-lg border border-rose-100">
                    ⚠️ 경고: 퇴직 후 연금 수령 전까지 무려 <strong>{68 - profile.retireAge}년</strong>의 소득 단절 크레바스가 발생하여 가구 대비책이 긴급히 필요합니다!
                  </p>
                ) : (
                  <p className="text-xs text-indigo-800 font-extrabold bg-indigo-50/50 p-2.5 rounded-lg border border-indigo-100">
                    ✓ 안심: 정년 예정이 68세보다 늦거나 동일하여 직접적인 소득 끊김 위험은 면제됩니다.
                  </p>
                )}
                <p className="text-[10px] text-slate-500 mt-1">
                  {ageData.suggestion}
                </p>
              </div>

              {/* 거시 재정 C */}
              <div className="p-4 bg-slate-50 rounded-xl border border-slate-200 space-y-2">
                <p className="text-xs font-extrabold text-slate-800 flex items-center gap-1">
                  <span className="w-1.5 h-3 bg-slate-500 rounded"></span>
                  3. 미래 후대 세금 청구서 예측 (2050년)
                </p>
                <div className="text-[10px] space-y-1 bg-white p-2.5 rounded-lg border border-slate-200 font-mono text-slate-600">
                  <div className="flex justify-between">
                    <span>보편 균등형(B-A):</span>
                    <span className="font-extrabold">54.10조 원</span>
                  </div>
                  <div className="flex justify-between">
                    <span>선별 차등형(B-B/C):</span>
                    <span className="font-extrabold">57.82조 원</span>
                  </div>
                  <div className="flex justify-between text-rose-600 pt-1 border-t">
                    <span>노인 보호 투자 편차:</span>
                    <span>+3.72조 원</span>
                  </div>
                </div>
                <p className="text-[10px] text-slate-500 leading-normal">
                  미리 60조 기금을 비축해 두는 <strong>B-C 계획</strong>이 타결되면, 2050년 조세 한도를 50조로 강력 통제하여 자녀의 파산을 예방할 수 있습니다.
                </p>
              </div>

              {/* 금융 위험 D */}
              <div className="p-4 bg-red-50/30 rounded-xl border border-red-100 space-y-2">
                <p className="text-xs font-extrabold text-red-950 flex items-center gap-1">
                  <TrendingDown className="w-4 h-4 text-red-600" />
                  4. 연 6.0% 적극 투자 성적 실패 위험
                </p>
                <p className="text-[11px] text-slate-650 leading-relaxed">
                  국민연금 N-C 안은 매년 연 6%의 초우수 해외 자산 실적을 가정합니다. 글로벌 금리 동결이나 금융 한파로 수익률이 5% 밑으로 떨어지면 기금 바닥 연장은 순식간에 불투명해집니다.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* 오른쪽: AI 상담 챗봇 및 소그룹 합의 기록지 */}
        <div className="xl:col-span-7 space-y-6">
          
          {/* AI 실시간 챗봇 */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden flex flex-col h-[380px]">
            <div className="bg-blue-950 text-white px-5 py-3 flex justify-between items-center shrink-0">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-amber-400" />
                <div>
                  <h4 className="text-xs md:text-sm font-extrabold text-white">AI 전담 연금설계사 1:1 라이브 대화방</h4>
                  <p className="text-[10px] text-slate-400">데이터 기반 중립 AI 브리핑</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setMessages([messages[0]])}
                className="p-1 text-slate-400 hover:text-white rounded hover:bg-slate-800 transition-all cursor-pointer"
                title="상담 리셋"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* 메시지 영역 */}
            <div className="flex-1 p-4 overflow-y-auto space-y-3.5 text-xs custom-scrollbar bg-slate-50/50">
              {messages.map((m) => (
                <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 shadow-sm leading-relaxed ${
                    m.role === "user"
                      ? "bg-blue-600 text-white rounded-br-none font-medium"
                      : "bg-white text-slate-800 border border-slate-200 rounded-bl-none markdown-body text-[11px]"
                  }`}>
                    {m.role === "user" ? (
                      <p className="whitespace-pre-line">{m.text}</p>
                    ) : (
                      <div className="prose prose-sm max-w-none text-slate-800">
                        <ReactMarkdown>{m.text}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex justify-start">
                  <div className="bg-white text-slate-500 border border-slate-200 rounded-xl rounded-bl-none px-3.5 py-2 flex items-center gap-2 shadow-sm text-[11px]">
                    <span className="w-1.5 h-1.5 bg-blue-600 rounded-full animate-ping"></span>
                    <span>AI 연금 전문가가 프로필 시나리오를 점검하고 있습니다...</span>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* 입력창 */}
            <form onSubmit={handleSendMessage} className="p-3 bg-white border-t border-slate-200 flex gap-2 shrink-0">
              <input
                id="workspace-chat-input"
                type="text"
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="예: 50대 가입자에게 P2가 미치는 장단점은? 60조 기금 고충..."
                className="flex-1 px-3.5 py-2 border border-slate-200 rounded-xl text-xs focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-600 bg-slate-50/50 focus:bg-white transition-all text-slate-800 font-medium"
                disabled={loading}
              />
              <button
                id="workspace-btn-send"
                type="submit"
                disabled={!inputText.trim() || loading}
                className={`p-2 rounded-xl text-white transition-all shrink-0 ${
                  inputText.trim() && !loading
                    ? "bg-blue-600 hover:bg-blue-700 cursor-pointer"
                    : "bg-slate-200 cursor-not-allowed"
                }`}
              >
                <Send className="w-4 h-4" />
              </button>
            </form>
          </div>

          {/* 소그룹 숙의 의사결정 기록지 */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="bg-slate-900 text-white p-5 flex items-center gap-2">
              <Scale className="w-4 h-4 text-blue-400" />
              <h4 className="text-xs font-extrabold uppercase tracking-wide text-white">
                실험 위원회 공적 합의 기록지
              </h4>
            </div>

            <div className="p-6 space-y-6">
              
              {/* Q1 */}
              <div className="space-y-2.5" id="delib-q1">
                <label className="text-xs font-extrabold text-slate-800 block leading-tight">
                  [합의 1] 미래 장기 연금 지속성을 위해, 연금 받는 개시 나이를 만 68세로 점차 상향하는 것에 합의하십니까? <span className="text-rose-500">*</span>
                </label>
                <div className="space-y-1.5">
                  {q1Options.map((opt) => (
                    <button
                      key={opt.value}
                      id={`delib-q1-${opt.value}`}
                      type="button"
                      onClick={() => setDelibQ1(opt.value)}
                      className={`w-full text-left p-2.5 rounded-xl border text-[11px] transition-all cursor-pointer ${
                        delibQ1 === opt.value
                          ? "border-blue-600 bg-blue-50/40 font-bold text-blue-900"
                          : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      <div className="font-extrabold">{opt.label}</div>
                      <div className="text-[10px] text-slate-400 font-medium mt-0.5">{opt.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Q2 */}
              <div className="space-y-2.5" id="delib-q2">
                <label className="text-xs font-extrabold text-slate-800 block leading-tight">
                  [합의 2] 만약 국가 세수에서 초반 매칭 준비금으로 100조 원만 융통 가능하다면, 어디에 먼저 적립해야 할까요? <span className="text-rose-500">*</span>
                </label>
                <div className="space-y-1.5">
                  {q2Options.map((opt) => (
                    <button
                      key={opt.value}
                      id={`delib-q2-${opt.value}`}
                      type="button"
                      onClick={() => setDelibQ2(opt.value)}
                      className={`w-full text-left p-2.5 rounded-xl border text-[11px] transition-all cursor-pointer ${
                        delibQ2 === opt.value
                          ? "border-blue-600 bg-blue-50/40 font-bold text-blue-900"
                          : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      <div className="font-extrabold">{opt.label}</div>
                      <div className="text-[10px] text-slate-400 font-medium mt-0.5">{opt.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Q3 */}
              <div className="space-y-2" id="delib-q3">
                <label className="text-xs font-extrabold text-slate-800 block">
                  [합의 3] 목표 자산수익률 연 6% 달성을 위한 글로벌 공격적 투자 추진 찬반 여부 <span className="text-rose-500">*</span>
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { value: "approve", label: "찬성 (투자 확대)" },
                    { value: "refuse", label: "반대 (안정성 확보)" },
                    { value: "conditional", label: "조건부 위험 관리" },
                  ].map((opt) => (
                    <button
                      key={opt.value}
                      id={`delib-q3-${opt.value}`}
                      type="button"
                      onClick={() => setDelibQ3(opt.value)}
                      className={`py-2 px-1 text-center text-[10px] font-extrabold rounded-lg border transition-all cursor-pointer ${
                        delibQ3 === opt.value
                          ? "bg-blue-600 border-blue-600 text-white shadow-sm"
                          : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Q4 */}
              <div className="space-y-2" id="delib-q4">
                <label className="text-xs font-extrabold text-slate-800 block leading-tight">
                  [합의 4] 생활이 가난한 노인층 보호를 위해, 비교적 고자산 노령자의 기초연금액을 월 20만 원으로 소폭 낮추고 어려운 이웃은 월 50만 원으로 넓히는 차등 분배에 동의하십니까? <span className="text-rose-500">*</span>
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { value: "fair", label: "찬성 (선택 복지)" },
                    { value: "unfair", label: "반대 (보편 평등)" },
                    { value: "neutral", label: "중립 / 보완책 요구" },
                  ].map((opt) => (
                    <button
                      key={opt.value}
                      id={`delib-q4-${opt.value}`}
                      type="button"
                      onClick={() => setDelibQ4(opt.value)}
                      className={`py-2 px-1 text-center text-[10px] font-extrabold rounded-lg border transition-all cursor-pointer ${
                        delibQ4 === opt.value
                          ? "bg-blue-600 border-blue-600 text-white shadow-sm"
                          : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 하단 진행 조율 완료 버튼 */}
              <div className="pt-4 border-t border-slate-200 flex flex-col md:flex-row justify-between items-center gap-3">
                <p className="text-[10px] text-slate-450 font-bold leading-normal">
                  💡 합의지 4개 질문에 모두 투표해 주셔야 AI 의견 기록이 저장되어 대망의 최종 투표창으로 연결됩니다.
                </p>
                <button
                  id="btn-workspace-complete"
                  disabled={!checkValidation()}
                  onClick={handleNextStep}
                  className={`w-full md:w-auto py-2.5 px-6 rounded-xl text-xs font-extrabold transition-all shadow-sm flex items-center justify-center gap-1 ${
                    checkValidation()
                      ? "bg-blue-600 text-white hover:bg-blue-700 hover:shadow cursor-pointer"
                      : "bg-slate-100 text-slate-400 cursor-not-allowed"
                  }`}
                >
                  기록 저장 및 4단계 최종 투표로
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>

            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
