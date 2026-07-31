import React, { useState, useRef, useEffect } from "react";
import { UserProfile, VoteData, ChatMessage } from "../types";
import { Send, Sparkles, AlertTriangle, ArrowRight, Info, Scale, Check, RefreshCw } from "lucide-react";
import ReactMarkdown from "react-markdown";

interface DeliberationStageProps {
  profile: UserProfile;
  votes: VoteData;
  setVotes: (votes: VoteData) => void;
  onNext: () => void;
}

export default function DeliberationStage({
  profile,
  votes,
  setVotes,
  onNext,
}: DeliberationStageProps) {
  // 질문 및 AI Chat 상태
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "model",
      text: `### 🎙️ 안녕하세요! 소그룹 대화방에 오신 것을 환영합니다.
저는 여러분의 토론과 궁금증 해결을 도울 **AI 연금 도우미**입니다.

내가 입력한 정보와 1차 투표 결과를 바탕으로 맞춤 대화를 나눌 준비가 되었습니다.
- **내 연령대**: ${profile.ageGroup || "미입력"}
- **내가 1차 투표에서 고른 패키지**: ${
        votes.integratedPackage === "P1"
          ? "패키지 P1 (나이유지·보편상향)"
          : votes.integratedPackage === "P2"
          ? "패키지 P2 (나이연장·차등상향)"
          : votes.integratedPackage === "P3"
          ? "패키지 P3 (나이연장·저축대비)"
          : "아직 고민 중"
      }

연금 받는 나이를 만 68세로 늦추는 것, 초반에 세금 저축(160조 원)을 추진하는 일, 투자 성적이 나쁠 때 생길 리스크 등 복잡해 보였던 수치나 개념에 대해 궁금한 점을 편하게 질문해 보세요! 쉽고 정직하게 답변해 드리겠습니다.`,
      timestamp: new Date(),
    },
  ]);
  const [inputText, setInputText] = useState("");
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // 숙의 의사결정 상태 (질문 1 ~ 4)
  const [delibQ1, setDelibQ1] = useState<string>(""); // 수급연령
  const [delibQ2, setDelibQ2] = useState<string>(""); // 초과세수 재원 배분
  const [delibQ3, setDelibQ3] = useState<string>(""); // 기금운용위험 찬반
  const [delibQ4, setDelibQ4] = useState<string>(""); // 기초연금 형평성

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

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
          history: messages.slice(1).map((m) => ({ role: m.role, text: m.text })), // 환영인사 제외 역사 전달
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
        throw new Error("답변 수신 실패");
      }
    } catch (err) {
      console.error(err);
      setMessages((prev) => [
        ...prev,
        {
          id: Math.random().toString(),
          role: "model",
          text: `### ❌ 오류가 발생했습니다.
AI API 서버와 통신 도중 에러가 생겼습니다. 개발자 설정이나 네트워크 구성을 체크해 주십시오. 
임시 안내로서, 국민연금 보험료 13% 인상 및 기초연금 미래 기금 적립 방안에 관해서는 1-2차 투표 화면과 현황 보고서 데이터를 재참조해 보시는 것을 적극 추천드립니다.`,
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
    // 숙의한 배분 결정 등을 votes 상태에 업데이트
    setVotes({
      ...votes,
      conflictResolution: delibQ2, // 질문 2의 세수배분 결과를 여기에 바인딩
    });
    onNext();
  };

  const q1Options = [
    { value: "65", label: "만 65세 유지 (지금처럼 받기)", desc: "은퇴하고 돈이 끊기는 시기를 없앱니다. 단, 미래 세대의 세금 부담이 커지는 것을 인정합니다." },
    { value: "66", label: "만 66세로 1살만 높이기", desc: "조금만 늦춰서 급격한 충격을 줄이는 중간 타협안입니다." },
    { value: "67", label: "만 67세로 2살 높이기", desc: "세대 간에 조금씩 부담을 골고루 나누어 가지는 안입니다." },
    { value: "68", label: "만 68세로 3살 높이기 (계획안 B, C)", desc: "연금 기금을 아주 오랫동안 튼튼하게 지키기 위해 받는 나이를 조금 더 늦춥니다." },
    { value: "differential", label: "하는 일이나 근로 능력에 따라 다르게 적용", desc: "몸을 많이 쓰는 힘든 육체 노동직 등은 일찍 받고, 사무직 등은 천천히 받도록 분리합니다." },
  ];

  const q2Options = [
    { value: "NP-100", label: "국민연금에 100조, 기초연금엔 0조", desc: "기초연금용 저축은 생략하고, 나라 예산을 국민연금 초반 저축에 전부 몰아줍니다." },
    { value: "NP-70_BP-30", label: "국민연금에 70조, 기초연금에 30조", desc: "국민연금에 더 중점을 두되, 기초연금에도 절반 수준의 저축을 시작합니다." },
    { value: "NP-50_BP-50", label: "국민연금에 50조, 기초연금에 50조", desc: "두 연금 모두 똑같이 절반씩 나누어 미래 준비금을 공평하게 세워줍니다." },
    { value: "NP-40_BP-60", label: "국민연금에 40조, 기초연금에 60조", desc: "기초연금용 목표치인 60조 원을 먼저 다 채우고, 국민연금 저축은 조금 줄입니다." },
    { value: "NO-FUND", label: "둘 다 초반 저축을 하지 않고 매년 세금으로 꼬박 때웁니다", desc: "국채 증가 부담을 무겁게 보아, 초반 저축 대신 매년 필요한 만큼만 그때그때 세금으로 충당합니다." },
  ];

  return (
    <div className="space-y-8 animate-fade-in" id="deliberation-stage-container">
      <div className="bg-white rounded-xl shadow-md border border-slate-200 p-6 md:p-8">
        <div className="border-l-4 border-indigo-600 pl-4 py-1 mb-6">
          <h2 className="text-xl md:text-2xl font-extrabold tracking-tight text-slate-900">5단계: 소그룹 AI 연금대화방 및 의사결정 기록지</h2>
          <p className="text-xs md:text-sm text-slate-500 mt-1.5 leading-relaxed">
            연금 개혁의 가장 민감한 4가지 핵심 안건을 스스로 숙고하고 해결책을 도출합니다. 궁금한 지점은 실시간 AI 대화창에 편하게 질문해 보세요.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* 왼쪽: AI Q&A 실시간 숙의실 (7 cols) */}
          <div className="lg:col-span-7 flex flex-col h-[600px] bg-slate-50/50 rounded-2xl border border-slate-200 overflow-hidden shadow-sm">
            {/* 챗봇 헤더 */}
            <div className="bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 text-white px-4 py-4 flex justify-between items-center flex-shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/20 flex items-center justify-center text-indigo-400">
                  <Sparkles className="w-4 h-4 text-amber-400" />
                </div>
                <div>
                  <h3 className="text-xs md:text-sm font-extrabold tracking-tight">AI 연금개혁 대화상담소</h3>
                  <p className="text-[10px] text-slate-400 font-medium">데이터 기반 중립 전문가 AI</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setMessages([messages[0]])}
                className="p-1.5 hover:bg-slate-800 rounded-lg transition-all text-slate-400 hover:text-white cursor-pointer"
                title="대화 초기화"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>

            {/* 메시지 리스트 */}
            <div className="flex-1 p-4 overflow-y-auto space-y-4 text-xs md:text-sm">
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 shadow-sm ${
                      m.role === "user"
                        ? "bg-indigo-600 text-white rounded-br-none"
                        : "bg-white text-slate-800 border border-slate-200 rounded-bl-none markdown-body"
                    }`}
                  >
                    {m.role === "user" ? (
                      <p className="whitespace-pre-line leading-relaxed">{m.text}</p>
                    ) : (
                      <ReactMarkdown>{m.text}</ReactMarkdown>
                    )}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex justify-start">
                  <div className="bg-white text-slate-500 border border-slate-200 rounded-2xl rounded-bl-none px-4 py-3 shadow-sm flex items-center gap-2">
                    <span className="w-2 h-2 bg-indigo-600 rounded-full animate-ping"></span>
                    <span className="text-xs text-slate-500">AI가 연금 장기 계획과 세무 고민을 분석하여 답변을 작성하고 있습니다...</span>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* 입력 폼 */}
            <form onSubmit={handleSendMessage} className="p-3.5 bg-white border-t border-slate-200 flex gap-2 flex-shrink-0">
              <input
                id="chat-input-field"
                type="text"
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="예: 만 68세 수급 시 소득 공백기 대안은 무엇인가요? 160조를 국채로 내면 이자가 세나요?"
                className="flex-1 px-4 py-2.5 border border-slate-200 rounded-xl text-slate-800 text-xs md:text-sm focus:outline-none focus:border-indigo-600 focus:ring-1 focus:ring-indigo-600"
                disabled={loading}
              />
              <button
                id="btn-chat-send"
                type="submit"
                disabled={!inputText.trim() || loading}
                className={`p-2.5 rounded-xl text-white transition-all ${
                  inputText.trim() && !loading
                    ? "bg-indigo-600 hover:bg-indigo-700 hover:scale-105 cursor-pointer"
                    : "bg-slate-200 cursor-not-allowed"
                }`}
              >
                <Send className="w-5 h-5" />
              </button>
            </form>
          </div>

          {/* 오른쪽: 소그룹 숙의 의사결정 시뮬레이터 (5 cols) */}
          <div className="lg:col-span-5 space-y-6">
            <div className="bg-slate-900 text-white p-4.5 rounded-xl border border-slate-800 shadow-sm">
              <h3 className="text-xs md:text-sm font-bold flex items-center gap-1.5 text-indigo-300 uppercase tracking-wider">
                <Scale className="w-5 h-5 text-indigo-400" />
                우리 토론방 의사결정 기록지
              </h3>
              <p className="text-[11px] text-slate-450 mt-1 leading-relaxed">
                숙의에 대한 내 생각과 소그룹 토론 의견을 반영하여 아래 4가지 항목을 모두 채워주셔야 다음 최종 투표로 넘어갈 수 있습니다.
              </p>
            </div>

            {/* 1. 수급연령 합의 */}
            <div className="p-4.5 bg-slate-50/50 border border-slate-200 rounded-xl space-y-2.5" id="delib-q1-container">
              <label className="text-xs font-bold text-slate-800 block leading-tight">
                [합의 1] 국민연금을 받는 시작 나이를 미래 세대를 위해 만 68세로 늦추는 방안에 어떻게 생각하시나요? <span className="text-red-500">*</span>
              </label>
              <div className="space-y-1.5">
                {q1Options.map((opt) => (
                  <button
                    key={opt.value}
                    id={`delib-q1-${opt.value}`}
                    type="button"
                    onClick={() => setDelibQ1(opt.value)}
                    className={`w-full py-2 px-3 text-[11px] rounded-lg border text-left transition-all cursor-pointer ${
                      delibQ1 === opt.value
                        ? "border-indigo-600 bg-indigo-50/50 text-indigo-900 font-extrabold shadow-sm"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-semibold">{opt.label}</div>
                    <div className="text-[10px] text-slate-400 font-normal mt-0.5">{opt.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* 2. 초과세수/초기재정 배분 시뮬레이터 */}
            <div className="p-4.5 bg-slate-50/50 border border-slate-200 rounded-xl space-y-2.5" id="delib-q2-container">
              <div className="flex items-start gap-1">
                <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                <label className="text-xs font-bold text-slate-800 block leading-tight">
                  [합의 2] 만약 초반에 안전판 저축으로 쓸 수 있는 나라 돈이 100조 원 한정되어 있다면, 어떻게 나누는 것이 좋을까요? <span className="text-red-500">*</span>
                </label>
              </div>
              <p className="text-[10px] text-slate-500 leading-tight">
                ※ 두 연금 모두 저축(총 160조)하려다 국고가 고갈되는 재정 충돌을 피하기 위해, 한정된 돈(100조)을 나누는 실질적인 고민입니다.
              </p>
              <div className="space-y-1.5">
                {q2Options.map((opt) => (
                  <button
                    key={opt.value}
                    id={`delib-q2-${opt.value}`}
                    type="button"
                    onClick={() => setDelibQ2(opt.value)}
                    className={`w-full py-2 px-3 text-[11px] rounded-lg border text-left transition-all cursor-pointer ${
                      delibQ2 === opt.value
                        ? "border-indigo-600 bg-indigo-50/50 text-indigo-900 font-extrabold shadow-sm"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-semibold">{opt.label}</div>
                    <div className="text-[10px] text-slate-400 font-normal mt-0.5">{opt.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* 3. 기금운용위험 수용 */}
            <div className="p-4.5 bg-slate-50/50 border border-slate-200 rounded-xl space-y-2.5" id="delib-q3-container">
              <label className="text-xs font-bold text-slate-800 block">
                [합의 3] 높은 목표 수익률 6%를 달성하기 위해, 전 세계 고수익/고위험 상품(해외주식 등)에 대한 공격적인 대규모 투자를 찬성하시나요? <span className="text-red-500">*</span>
              </label>
              <div className="flex gap-2">
                {[
                  { value: "approve", label: "찬성 (투자수익 우선)" },
                  { value: "refuse", label: "반대 (안정성 우선)" },
                  { value: "conditional", label: "조건부 찬성 (위험 관리)" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    id={`delib-q3-${opt.value}`}
                    type="button"
                    onClick={() => setDelibQ3(opt.value)}
                    className={`flex-1 py-2.5 text-[10px] rounded-lg border text-center transition-all font-bold cursor-pointer ${
                      delibQ3 === opt.value
                        ? "border-indigo-600 bg-indigo-50/50 text-indigo-900 shadow-sm"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 4. 기초연금 차등 수혜 형평성 */}
            <div className="p-4.5 bg-slate-50/50 border border-slate-200 rounded-xl space-y-2.5" id="delib-q4-container">
              <label className="text-xs font-bold text-slate-800 block leading-tight">
                [합의 4] 형편이 어려운 어르신께 월 50만 원을 밀어드리기 위해, 비교적 생활이 괜찮으신 분들의 기초연금을 월 20만 원으로 줄이는 차등 지급에 동의하시나요? <span className="text-red-500">*</span>
              </label>
              <div className="flex gap-2">
                {[
                  { value: "fair", label: "찬성 (어려운 분 돕기 최우선)" },
                  { value: "unfair", label: "반대 (다 같이 골고루 지급)" },
                  { value: "neutral", label: "중립 (보완 대책 필요)" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    id={`delib-q4-${opt.value}`}
                    type="button"
                    onClick={() => setDelibQ4(opt.value)}
                    className={`flex-1 py-2.5 text-[10px] rounded-lg border text-center transition-all font-bold cursor-pointer ${
                      delibQ4 === opt.value
                        ? "border-indigo-600 bg-indigo-50/50 text-indigo-900 shadow-sm"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* 진행 통제 바 */}
        <div className="mt-8 flex flex-col md:flex-row gap-4 justify-between items-center border-t border-slate-200 pt-6">
          <p className="text-xs text-slate-450 font-semibold flex items-center gap-1.5">
            <Info className="w-4 h-4 text-indigo-600" />
            의사결정 기록지의 4가지 질문에 모두 답하셔야 마지막 2차 최종 투표를 하실 수 있습니다.
          </p>

          <button
            id="btn-delib-complete"
            disabled={!checkValidation()}
            onClick={handleNextStep}
            className={`w-full md:w-auto py-3 px-6 rounded-xl text-xs md:text-sm font-bold shadow-sm transition-all flex items-center justify-center gap-1.5 ${
              checkValidation()
                ? "bg-indigo-600 hover:bg-indigo-700 text-white cursor-pointer hover:shadow"
                : "bg-slate-100 text-slate-400 cursor-not-allowed"
            }`}
          >
            6단계: 숙의 후 최종 투표 진행하기
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
