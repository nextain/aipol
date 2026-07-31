import React, { useState, useEffect } from "react";
import { UserProfile, PerceptionAnswers, KnowledgeAnswers, VoteData } from "./types";
import PreSurvey from "./components/PreSurvey";
import ReformBoard from "./components/ReformBoard";
import DeliberationWorkspace from "./components/DeliberationWorkspace";
import FinalBallotAndResults from "./components/FinalBallotAndResults";
import { Landmark, Clock, Award, ChevronRight, RefreshCw, CheckCircle } from "lucide-react";

const initialProfile: UserProfile = {
  ageGroup: "",
  incomeLevel: "",
  jobType: "",
  isMember: "",
  retireAge: 60,
  basicPensionEligible: "",
};

const initialPerception: PerceptionAnswers = {
  q1: 0,
  q2: 0,
  q3: 0,
  q4: 0,
  q5: 0,
  q6: 0,
  q7: 0,
  q8: 0,
};

const initialKnowledge: KnowledgeAnswers = {
  premiumRate: "",
  replacementRate: "",
  fundingDifference: "",
  fundMeaning: "",
  basicTarget: "",
};

const initialVote: VoteData = {
  nationalPension: "N-B",
  nationalConfidence: 80,
  nationalFairness: 5,
  nationalBenefit: 5,
  nationalFeasibility: 5,
  nationalReason: "",
  basicPension: "B-C",
  basicConfidence: 80,
  basicFairness: 5,
  basicBenefit: 5,
  basicFeasibility: 5,
  basicReason: "",
  integratedPackage: "P3",
  acceptAsGovernment: 5,
  acceptForSociety: 6,
  generationalFairness: 6,
  poorProtection: 5,
  sustainability: 6,
  riskManageable: 5,
};

export default function App() {
  const [step, setStep] = useState<number>(0);

  // 데이터 상태
  const [profile, setProfile] = useState<UserProfile>(initialProfile);
  const [perception, setPerception] = useState<PerceptionAnswers>(initialPerception);
  const [knowledge, setKnowledge] = useState<KnowledgeAnswers>(initialKnowledge);
  const [firstVote, setFirstVote] = useState<VoteData>(initialVote);

  // 숙의실험 경과 시간 타이머 (가상 세션 타이머)
  const [seconds, setSeconds] = useState<number>(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setSeconds((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // 분:초 포맷터
  const formatTime = (totalSeconds: number) => {
    const m = Math.floor(totalSeconds / 60);
    const s = totalSeconds % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // 실험 가이드라인 단계 정보 (4단계 압축 구성)
  const stages = [
    { index: 0, label: "1. 사전조사", time: "10분" },
    { index: 1, label: "2. 시뮬레이션·1차 투표", time: "20분" },
    { index: 2, label: "3. AI 진단·소그룹 토론", time: "25분" },
    { index: 3, label: "4. 최종 투표·결과 대시보드", time: "15분" },
  ];

  const handleRestart = () => {
    if (window.confirm("시뮬레이터를 초기화하고 사전조사 단계부터 다시 진행하시겠습니까?")) {
      setStep(0);
      setProfile(initialProfile);
      setPerception(initialPerception);
      setKnowledge(initialKnowledge);
      setFirstVote(initialVote);
      setSeconds(0);
    }
  };

  return (
    <div className="h-screen w-full bg-slate-50 flex flex-col text-slate-900 font-sans overflow-hidden" id="app-root">
      {/* 글로벌 상단 내비게이션 바 */}
      <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 md:px-8 shadow-sm shrink-0" id="main-header">
        <div className="flex items-center gap-3">
          <div className="bg-blue-600 text-white p-2 rounded-lg shadow-sm" id="logo-icon">
            <Landmark className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-sm md:text-base font-extrabold tracking-tight text-slate-900">공적연금개혁 AI 국민숙의실험실</h1>
            <p className="text-[9px] text-slate-400 font-bold uppercase tracking-wider">National Pension Reform AI Deliberation Lab</p>
          </div>
        </div>

        {/* 상단 4단계 스태퍼 */}
        <nav className="hidden lg:flex space-x-1.5" id="header-navigation-stepper">
          {stages.map((stage) => {
            const isCurrent = step === stage.index;
            const isPassed = step > stage.index;
            return (
              <button
                key={stage.index}
                onClick={() => {
                  if (stage.index <= step) setStep(stage.index);
                }}
                className={`flex items-center px-4 py-1 rounded-full text-xs font-bold transition-all ${
                  isCurrent
                    ? "bg-blue-600 text-white shadow-sm"
                    : isPassed
                    ? "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    : "bg-slate-50 text-slate-300 italic cursor-not-allowed"
                }`}
                disabled={stage.index > step}
              >
                <span>{stage.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="flex items-center gap-4">
          {/* 가상 경과 시계 */}
          <div className="bg-slate-50 px-3 py-1.5 rounded-lg border border-slate-200 flex items-center gap-1.5 text-xs font-semibold text-slate-700 shadow-inner" id="timer-badge">
            <Clock className="w-3.5 h-3.5 text-blue-600 animate-pulse" />
            <span className="font-mono text-blue-700 font-bold">{formatTime(seconds)}</span>
          </div>

          <button
            id="btn-header-reset"
            onClick={handleRestart}
            className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-950 font-bold py-1.5 px-2.5 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg transition-all shadow-sm cursor-pointer"
          >
            <RefreshCw className="w-3 h-3" />
            <span className="hidden sm:inline">실험 리셋</span>
          </button>
        </div>
      </header>

      {/* 모바일용 스태퍼 진행률 표시바 */}
      <div className="lg:hidden bg-slate-900 text-white border-b border-slate-950 px-4 py-2 overflow-x-auto flex items-center gap-3 scrollbar-none shrink-0" id="progress-stepper-bar">
        {stages.map((stage) => {
          const isCurrent = step === stage.index;
          const isPassed = step > stage.index;
          return (
            <div
              key={stage.index}
              className={`flex items-center gap-1 flex-shrink-0 text-[10px] font-bold transition-all py-1 px-2.5 rounded-full ${
                isCurrent
                  ? "bg-blue-600 text-white font-extrabold shadow"
                  : isPassed
                  ? "text-blue-300 font-bold"
                  : "text-slate-500"
              }`}
            >
              <span>{stage.label.split(". ")[1]}</span>
              {stage.index < 3 && <ChevronRight className="w-2.5 h-2.5 text-slate-700 ml-1" />}
            </div>
          );
        })}
      </div>

      {/* 메인 2단 스플릿 레이아웃 (좌: 참가자 컨텍스트 사이드바, 우: 개별 컨텐츠 영역) */}
      <main className="flex-1 flex overflow-hidden">
        {/* Sidebar: Participant Context */}
        <aside className="hidden lg:flex w-72 bg-white border-r border-slate-200 flex-col shrink-0 overflow-y-auto" id="participant-sidebar">
          <div className="p-5 space-y-5">
            <div>
              <label className="text-[9px] font-extrabold text-slate-400 uppercase tracking-wider block mb-2">
                나의 참여 Blueprint
              </label>
              <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2 shadow-inner">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-slate-500 font-bold">세대 분류</span>
                  <span className="font-extrabold text-slate-800">
                    {profile.ageGroup ? `${profile.ageGroup}대` : "사전조사 작성 중"}
                  </span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-slate-500 font-bold">정회원 자격</span>
                  <span className="font-extrabold text-slate-800">
                    {profile.isMember === "yes" ? "국민연금 납부단" : profile.isMember === "no" ? "기타 수급자" : "사전조사 작성 중"}
                  </span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-slate-500 font-bold">정년 퇴직</span>
                  <span className="font-extrabold text-slate-800">
                    {profile.retireAge ? `만 ${profile.retireAge}세 은퇴` : "미지정"}
                  </span>
                </div>
              </div>
            </div>

            <div>
              <label className="text-[9px] font-extrabold text-slate-400 uppercase tracking-wider block mb-2">
                1차 지지 계획안
              </label>
              {step >= 2 && firstVote.integratedPackage ? (
                <div className="bg-blue-50/60 border border-blue-100 rounded-xl p-3.5 space-y-1.5 shadow-sm">
                  <div className="text-blue-900 font-extrabold text-xs flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-600"></span>
                    {firstVote.integratedPackage === "P1" && "P1 (나이유지·모두균등)"}
                    {firstVote.integratedPackage === "P2" && "P2 (나이연장·소득차등)"}
                    {firstVote.integratedPackage === "P3" && "P3 (나이연장·저축대비)"}
                    {firstVote.integratedPackage === "NONE" && "적합 패키지 없음"}
                  </div>
                  <p className="text-[10px] text-slate-650 leading-relaxed font-medium">
                    {firstVote.integratedPackage === "P1" && "보험료를 13%로 연내 인상하고 개시일 만 65세 지키며, 고른 연금 증액에 주력합니다."}
                    {firstVote.integratedPackage === "P2" && "수령 개시를 만 68세로 늦추는 상향 조정에 동참하는 대신, 취약 노령자에 월 50만 원 집중 지원을 보강합니다."}
                    {firstVote.integratedPackage === "P3" && "수령 개시를 만 68세로 미루고, 선제적인 100조 국고 저축 및 목표 수익률 6% 달성을 위한 글로벌 적극 투자를 도모합니다."}
                  </p>
                </div>
              ) : (
                <div className="bg-slate-50 border border-dashed border-slate-200 rounded-xl p-4 text-center">
                  <span className="text-xs text-slate-400 font-bold">2단계 1차 투표 시 결정</span>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <label className="text-[9px] font-extrabold text-slate-400 uppercase tracking-wider block">
                나의 예측 부담 구간
              </label>
              <div className="flex flex-col space-y-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-slate-500 font-bold">보험료율 수치</span>
                  <span className="text-rose-600 font-extrabold bg-rose-50 px-2 py-0.5 rounded-full text-[10px]">
                    {step >= 1 ? "9% → 13% 인상" : "9% (현행 수준)"}
                  </span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-slate-500 font-bold">수급개시 시기</span>
                  <span className="font-extrabold text-slate-700 bg-slate-100 px-2 py-0.5 rounded-full text-[10px]">
                    {step >= 2 && (firstVote.integratedPackage === "P2" || firstVote.integratedPackage === "P3") ? "만 68세 개시" : "만 65세 유지"}
                  </span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-slate-500 font-bold">소득 구간</span>
                  <span className="font-extrabold text-blue-700 bg-blue-50 px-2 py-0.5 rounded-full text-[10px]">
                    {profile.incomeLevel === "under_2m" && "200만 미만"}
                    {profile.incomeLevel === "2m_4m" && "200만~400만"}
                    {profile.incomeLevel === "4m_6m" && "400만~600만"}
                    {profile.incomeLevel === "6m_8m" && "600만~800만"}
                    {profile.incomeLevel === "over_8m" && "800만 이상"}
                    {!profile.incomeLevel && "미작성"}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-auto p-4 border-t border-slate-150 bg-slate-50">
            <div className="text-[10px] text-slate-400 mb-3 leading-snug font-medium">
              ※ 대한민국 공정연금연구 위원회의 국고 시뮬레이션 및 데이터 세분화 패키지에 근거합니다.
            </div>
            <button
              onClick={() => setStep(0)}
              className="w-full py-2 bg-white border border-slate-200 hover:border-slate-300 rounded-xl text-xs font-bold text-slate-600 hover:text-slate-800 hover:bg-slate-100 transition-all shadow-sm flex items-center justify-center gap-1 cursor-pointer"
            >
              사전 프로필 정보 변경
            </button>
          </div>
        </aside>

        {/* Content Area */}
        <div className="flex-1 flex flex-col p-6 md:p-8 space-y-6 overflow-y-auto bg-slate-50" id="main-scroll-content">
          <div className="max-w-5xl w-full mx-auto space-y-6">
            
            {step === 0 && (
              <PreSurvey
                profile={profile}
                setProfile={setProfile}
                perception={perception}
                setPerception={setPerception}
                knowledge={knowledge}
                setKnowledge={setKnowledge}
                onNext={() => setStep(1)}
              />
            )}

            {step === 1 && (
              <ReformBoard
                voteData={firstVote}
                setVoteData={setFirstVote}
                onComplete={(data) => {
                  setFirstVote(data);
                  setStep(2);
                }}
              />
            )}

            {step === 2 && (
              <DeliberationWorkspace
                profile={profile}
                votes={firstVote}
                setVotes={setFirstVote}
                onNext={() => setStep(3)}
              />
            )}

            {step === 3 && (
              <FinalBallotAndResults
                profile={profile}
                firstVote={firstVote}
                onRestart={() => {
                  setStep(0);
                  setProfile(initialProfile);
                  setPerception(initialPerception);
                  setKnowledge(initialKnowledge);
                  setFirstVote(initialVote);
                  setSeconds(0);
                }}
              />
            )}

            {/* Content clean footer */}
            <footer className="pt-8 pb-4 text-center text-[11px] text-slate-400 border-t border-slate-200/60" id="content-inner-footer">
              <div className="flex flex-col sm:flex-row items-center justify-between gap-3 font-medium">
                <p>© 2026 대한민국 공적연금개혁 국책연구지원 연금숙의실험실.</p>
                <div className="flex gap-4 text-slate-400">
                  <span className="hover:text-blue-600 transition-all cursor-pointer">이용약관</span>
                  <span className="hover:text-blue-600 transition-all cursor-pointer">개인정보처리방침</span>
                </div>
              </div>
            </footer>
          </div>
        </div>
      </main>
    </div>
  );
}

