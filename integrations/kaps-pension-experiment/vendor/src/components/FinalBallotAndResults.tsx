import React, { useState } from "react";
import { UserProfile, VoteData, NationalOption, BasicOption, IntegratedOption } from "../types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
} from "recharts";
import {
  Award,
  RefreshCw,
  BarChart2,
  CheckCircle,
  Users,
  Activity,
  Sparkles,
  AlertTriangle,
  ArrowRight,
  ShieldAlert,
} from "lucide-react";

interface FinalBallotAndResultsProps {
  profile: UserProfile;
  firstVote: VoteData;
  onRestart: () => void;
}

export default function FinalBallotAndResults({
  profile,
  firstVote,
  onRestart,
}: FinalBallotAndResultsProps) {
  const [submitted, setSubmitted] = useState(false);

  // --- Part 1: 2nd Vote State ---
  const [nationalPension, setNationalPension] = useState<NationalOption>("N-B");
  const [nationalConfidence, setNationalConfidence] = useState<number>(80);
  const [basicPension, setBasicPension] = useState<BasicOption>("B-C");
  const [basicConfidence, setBasicConfidence] = useState<number>(80);
  const [integratedPackage, setIntegratedPackage] = useState<IntegratedOption>("P3");

  // Conflict state
  const [conflictResolution, setConflictResolution] = useState<string>("opt4");

  // Value preferences
  const [acceptAsGovernment, setAcceptAsGovernment] = useState<number>(5);
  const [acceptForSociety, setAcceptForSociety] = useState<number>(6);
  const [generationalFairness, setGenerationalFairness] = useState<number>(6);
  const [poorProtection, setPoorProtection] = useState<number>(5);
  const [sustainability, setSustainability] = useState<number>(6);
  const [riskManageable, setRiskManageable] = useState<number>(5);

  const [secondVoteResult, setSecondVoteResult] = useState<VoteData | null>(null);

  const isConflictingCombo = nationalPension === "N-B" && basicPension === "B-C";

  const handleSubmitVote = () => {
    const finalVote: VoteData = {
      ...firstVote,
      nationalPension,
      nationalConfidence,
      basicPension,
      basicConfidence,
      integratedPackage,
      conflictResolution: isConflictingCombo ? conflictResolution : "",
      acceptAsGovernment,
      acceptForSociety,
      generationalFairness,
      poorProtection,
      sustainability,
      riskManageable,
    };
    setSecondVoteResult(finalVote);
    setSubmitted(true);
  };

  // --- Part 2: Statistical Comparison Data ---
  const nationalComparisonData = [
    { name: "N-A (65세유지·세원)", first: 45, second: 30 },
    { name: "N-B (68세·안정적저축)", first: 25, second: 35 },
    { name: "N-C (68세·글로벌투자)", first: 15, second: 27 },
    { name: "유보/기타", first: 15, second: 8 },
  ];

  const basicComparisonData = [
    { name: "B-A (균등 40만)", first: 50, second: 35 },
    { name: "B-B (취약 차등)", first: 30, second: 31 },
    { name: "B-C (차등+저축)", first: 10, second: 28 },
    { name: "유보/기타", first: 10, second: 6 },
  ];

  const packageComparisonData = [
    { name: "P1 (보편유지)", first: 48, second: 33 },
    { name: "P2 (차등집중)", first: 28, second: 36 },
    { name: "P3 (저축투자)", first: 12, second: 25 },
    { name: "유보/기타", first: 12, second: 6 },
  ];

  // If not submitted, render the Ballot & Survey
  if (!submitted) {
    return (
      <div className="space-y-6 animate-fade-in" id="final-ballot-root">
        <div className="bg-slate-900 text-white p-6 rounded-2xl border border-slate-800">
          <div className="flex items-center gap-2 text-blue-400 font-bold text-xs uppercase tracking-wider">
            <Sparkles className="w-4 h-4 text-amber-400" />
            <span>Step 4 of 4: Final Vote</span>
          </div>
          <h2 className="text-xl md:text-2xl font-extrabold tracking-tight mt-1.5">
            숙의를 완료한 나의 최종 2차 투표 및 가치관 측정
          </h2>
          <p className="text-xs text-slate-300 mt-1 leading-relaxed">
            전담 AI 세무 전문가와 맞춤 분석을 마친 결과를 반영하여, 보다 다차원적인 공공 합의점에 도달하기 위한 최종 투표를 시행합니다.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          
          {/* 왼쪽: 2차 투표 용지 (7 cols) */}
          <div className="lg:col-span-7 bg-white p-6 rounded-2xl border border-slate-200 space-y-6">
            <h3 className="text-sm font-extrabold text-slate-800 border-b pb-3 flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-blue-600"></span>
              2차 최종 비밀 투표지 (Second Ballot)
            </h3>

            {/* 국민연금안 */}
            <div className="space-y-3">
              <label className="text-xs font-extrabold text-slate-700 block">
                ① 나의 최종 국민연금 개혁 대안 선택
              </label>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                {[
                  { value: "N-A", label: "N-A 안 (수령 65세·국비)", desc: "현행 연령 유지 및 미래 세금 충당" },
                  { value: "N-B", label: "N-B 안 (수령 68세·100조)", desc: "개시 68세 연기 및 초반 국고 저축" },
                  { value: "N-C", label: "N-C 안 (수령 68세·투자)", desc: "개시 68세 연기 및 연 6% 투자 우선" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setNationalPension(opt.value as NationalOption)}
                    className={`p-3 text-left rounded-xl border text-xs transition-all cursor-pointer ${
                      nationalPension === opt.value
                        ? "border-blue-600 bg-blue-50/40 text-blue-900 font-bold shadow-sm"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-extrabold">{opt.label}</div>
                    <div className="text-[10px] text-slate-400 font-medium mt-1 leading-tight">{opt.desc}</div>
                  </button>
                ))}
              </div>

              {/* 확신도 슬라이더 */}
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-1.5">
                <div className="flex justify-between items-center text-[11px] font-bold text-slate-600">
                  <span>해당 선택에 대한 최종 확신도:</span>
                  <span className="text-blue-600 font-mono text-xs">{nationalConfidence}%</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="5"
                  value={nationalConfidence}
                  onChange={(e) => setNationalConfidence(Number(e.target.value))}
                  className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                />
              </div>
            </div>

            {/* 기초연금안 */}
            <div className="space-y-3">
              <label className="text-xs font-extrabold text-slate-700 block">
                ② 나의 최종 기초연금 개혁 대안 선택
              </label>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                {[
                  { value: "B-A", label: "B-A 안 (균등 40만)", desc: "하위 70% 골고루 40만 원 인상" },
                  { value: "B-B", label: "B-B 안 (차등 분배)", desc: "어려운 분 50만 원, 여유 어르신 20만 원" },
                  { value: "B-C", label: "B-C 안 (차등+60조)", desc: "차등 분배 및 60조 원 기금 미리 저축" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setBasicPension(opt.value as BasicOption)}
                    className={`p-3 text-left rounded-xl border text-xs transition-all cursor-pointer ${
                      basicPension === opt.value
                        ? "border-blue-600 bg-blue-50/40 text-blue-900 font-bold shadow-sm"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-extrabold">{opt.label}</div>
                    <div className="text-[10px] text-slate-400 font-medium mt-1 leading-tight">{opt.desc}</div>
                  </button>
                ))}
              </div>

              {/* 확신도 슬라이더 */}
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-1.5">
                <div className="flex justify-between items-center text-[11px] font-bold text-slate-600">
                  <span>기초연금 대안에 대한 확신도:</span>
                  <span className="text-blue-600 font-mono text-xs">{basicConfidence}%</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="5"
                  value={basicConfidence}
                  onChange={(e) => setBasicConfidence(Number(e.target.value))}
                  className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                />
              </div>
            </div>

            {/* 통합 패키지안 */}
            <div className="space-y-3">
              <label className="text-xs font-extrabold text-slate-700 block">
                ③ 나의 최종 지지 종합 개혁 패키지
              </label>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                {[
                  { value: "P1", label: "패키지 P1", desc: "나이유지 및 보편 수급 상향" },
                  { value: "P2", label: "패키지 P2", desc: "나이연장 및 소득 차등 분배 집중" },
                  { value: "P3", label: "패키지 P3", desc: "나이연장 및 선제 저축·투자 비축" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setIntegratedPackage(opt.value as IntegratedOption)}
                    className={`p-3 text-left rounded-xl border text-xs transition-all cursor-pointer ${
                      integratedPackage === opt.value
                        ? "border-blue-600 bg-blue-50/40 text-blue-900 font-bold shadow-sm"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-extrabold">{opt.label}</div>
                    <div className="text-[10px] text-slate-400 font-medium mt-1 leading-tight">{opt.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* 160조 예산 충돌 해결 시나리오 (N-B + B-C 조건형 노출) */}
            {isConflictingCombo && (
              <div className="p-4 bg-amber-50 rounded-xl border border-amber-200 space-y-3 animate-fade-in">
                <div className="flex items-center gap-1.5 text-amber-800 font-bold text-xs">
                  <ShieldAlert className="w-4 h-4 text-amber-600" />
                  <span>[최종 완화 점검] 160조 원 재정 충돌 발생 우려</span>
                </div>
                <p className="text-[11px] text-slate-600 leading-normal">
                  국민연금 선제 저축(100조)과 기초연금 저축(60조)을 함께 가동하는 조합입니다. 국고 부담을 줄이기 위한 귀하의 완화 대안은 무엇입니까?
                </p>
                <div className="space-y-1.5">
                  {[
                    { value: "opt1", label: "옵션 1: 국채 발행 감수", desc: "국채 160조 원을 적극 발행해 초기에 무조건 완수" },
                    { value: "opt2", label: "옵션 2: 국민연금 저축 소폭 축소", desc: "국민연금 저축을 70조 수준으로 다이어트" },
                    { value: "opt3", label: "옵션 3: 기초연금 저축 규모 보류", desc: "기초연금은 저축 없이 차등지급만 바로 수행" },
                    { value: "opt4", label: "옵션 4: 연차별 분할 비축 상환", desc: "160조의 비축을 연단위 상환으로 분산 감수" },
                  ].map((resOpt) => (
                    <button
                      key={resOpt.value}
                      type="button"
                      onClick={() => setConflictResolution(resOpt.value)}
                      className={`w-full text-left p-2.5 rounded-lg border text-[11px] transition-all cursor-pointer ${
                        conflictResolution === resOpt.value
                          ? "border-amber-600 bg-amber-50 text-amber-900 font-bold"
                          : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      <span className="font-extrabold">{resOpt.label}</span> - {resOpt.desc}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 오른쪽: 가치 수용성 다차원 측정 (5 cols) */}
          <div className="lg:col-span-5 bg-white p-6 rounded-2xl border border-slate-200 space-y-5">
            <h3 className="text-sm font-extrabold text-slate-800 border-b pb-3 flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-blue-600"></span>
              최종 정책 수용도 및 가치 분석 (1~7점)
            </h3>
            <p className="text-[10px] text-slate-500 leading-normal">
              숙의 과정을 통해 변모한 정책 가치관 수치를 정밀 배분합니다. 슬라이더를 통해 등급을 선택해 주세요.
            </p>

            {/* Value Inputs */}
            {[
              { label: "정부 및 공적 안전망 신뢰도", value: acceptAsGovernment, set: setAcceptAsGovernment },
              { label: "사회적 이웃 상생 배려심", value: acceptForSociety, set: setAcceptForSociety },
              { label: "청년-고령층 세대 균형성", value: generationalFairness, set: setGenerationalFairness },
              { label: "취약 빈곤 노인 집중 보호도", value: poorProtection, set: setPoorProtection },
              { label: "기금 소멸 예방 및 지속가능성", value: sustainability, set: setSustainability },
              { label: "글로벌 투자 적극성 / 위험 수용도", value: riskManageable, set: setRiskManageable },
            ].map((v, idx) => (
              <div key={idx} className="space-y-1.5 p-3.5 bg-slate-50 rounded-xl border border-slate-200/60">
                <div className="flex justify-between items-center text-[10px] font-extrabold text-slate-700">
                  <span>{v.label}</span>
                  <span className="text-blue-600 font-mono text-xs">{v.value}점</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="7"
                  step="1"
                  value={v.value}
                  onChange={(e) => v.set(Number(e.target.value))}
                  className="w-full h-1 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                />
              </div>
            ))}

            <button
              id="btn-submit-final-vote"
              type="button"
              onClick={handleSubmitVote}
              className="w-full mt-4 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold transition-all shadow hover:shadow-md flex items-center justify-center gap-1.5 cursor-pointer"
            >
              종합 보고서 생성 및 최종 통계 보기
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>

        </div>
      </div>
    );
  }

  // If submitted, render ResultDashboard
  const valueRadarData = [
    { subject: "정부안 신뢰도", 1: firstVote.acceptAsGovernment, 2: secondVoteResult?.acceptAsGovernment || 5, fullMark: 7 },
    { subject: "이웃 상생심", 1: firstVote.acceptForSociety, 2: secondVoteResult?.acceptForSociety || 6, fullMark: 7 },
    { subject: "세대간 공평", 1: firstVote.generationalFairness, 2: secondVoteResult?.generationalFairness || 6, fullMark: 7 },
    { subject: "취약 보호도", 1: firstVote.poorProtection, 2: secondVoteResult?.poorProtection || 5, fullMark: 7 },
    { subject: "장기 지속성", 1: firstVote.sustainability, 2: secondVoteResult?.sustainability || 6, fullMark: 7 },
    { subject: "투자 모험성", 1: firstVote.riskManageable, 2: secondVoteResult?.riskManageable || 5, fullMark: 7 },
  ];

  const isNationalMoved = firstVote.nationalPension !== secondVoteResult?.nationalPension;
  const isBasicMoved = firstVote.basicPension !== secondVoteResult?.basicPension;
  const isPackageMoved = firstVote.integratedPackage !== secondVoteResult?.integratedPackage;

  return (
    <div className="space-y-6 animate-fade-in" id="result-dashboard-root">
      
      {/* 상단 리포트 머리글 */}
      <div className="bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-white p-6 md:p-8 rounded-2xl shadow-lg flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
        <div className="space-y-1.5">
          <div className="inline-flex items-center gap-1.5 bg-blue-500/20 text-blue-300 text-[10px] font-extrabold px-3 py-1 rounded-full uppercase border border-blue-500/30">
            <Award className="w-3.5 h-3.5 text-amber-400" />
            <span>AI Deliberation Analytics</span>
          </div>
          <h2 className="text-xl md:text-2xl font-extrabold tracking-tight">
            연금개혁 나의 1차·2차 투표 통합 분석 보고서
          </h2>
          <p className="text-xs text-slate-300 mt-1 leading-relaxed">
            학습과 전문가 AI Consultation을 통해 변모한 귀하의 투표 궤적과 다른 배심원단 500명의 생각을 대조 분석한 공공 대시보드입니다.
          </p>
        </div>
        <button
          id="btn-restart-simulation"
          onClick={onRestart}
          className="flex items-center gap-1.5 px-5 py-3 bg-blue-600 hover:bg-blue-700 transition-all font-extrabold rounded-xl text-xs shadow hover:shadow-md cursor-pointer text-white shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          처음부터 다시 체험하기
        </button>
      </div>

      {/* 개인 투표 추적 (1차 vs 2차) Bento Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        
        {/* 국민연금 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center border-b border-slate-100 pb-2.5">
              <h4 className="font-extrabold text-slate-800 text-xs flex items-center gap-1.5 uppercase tracking-wide">
                <Users className="w-4 h-4 text-blue-600" />
                국민연금 생각 비교
              </h4>
              <span className={`text-[9px] font-extrabold px-2 py-0.5 rounded ${
                isNationalMoved ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-500"
              }`}>
                {isNationalMoved ? "의견 이동함" : "의견 고정함"}
              </span>
            </div>
            <div className="space-y-2 mt-3.5">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                <p className="text-[9px] text-slate-400 font-extrabold uppercase">1차 투표 (숙의 전)</p>
                <p className="text-xs font-extrabold text-slate-700 mt-1">
                  {firstVote.nationalPension === "N-A" && "N-A (수령 65세·국비 부담)"}
                  {firstVote.nationalPension === "N-B" && "N-B (수령 68세·100조 저축)"}
                  {firstVote.nationalPension === "N-C" && "N-C (수령 68세·수익률 6%)"}
                  {firstVote.nationalPension === "NONE" && "적합 대안 없음"}
                  {firstVote.nationalPension === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
              <div className="p-3 bg-blue-50/30 rounded-xl border border-blue-100">
                <p className="text-[9px] text-blue-500 font-extrabold uppercase">2차 투표 (숙의 후)</p>
                <p className="text-xs font-extrabold text-blue-900 mt-1">
                  {secondVoteResult?.nationalPension === "N-A" && "N-A (수령 65세·국비 부담)"}
                  {secondVoteResult?.nationalPension === "N-B" && "N-B (수령 68세·100조 저축)"}
                  {secondVoteResult?.nationalPension === "N-C" && "N-C (수령 68세·수익률 6%)"}
                  {secondVoteResult?.nationalPension === "NONE" && "적합 대안 없음"}
                  {secondVoteResult?.nationalPension === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
            </div>
          </div>
          <p className="text-[10px] text-slate-500 pt-3 border-t border-slate-100 mt-3 font-semibold">
            확신 점수 변화: {firstVote.nationalConfidence}% → {secondVoteResult?.nationalConfidence}%
          </p>
        </div>

        {/* 기초연금 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center border-b border-slate-100 pb-2.5">
              <h4 className="font-extrabold text-slate-800 text-xs flex items-center gap-1.5 uppercase tracking-wide">
                <Users className="w-4 h-4 text-blue-600" />
                기초연금 생각 비교
              </h4>
              <span className={`text-[9px] font-extrabold px-2 py-0.5 rounded ${
                isBasicMoved ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-500"
              }`}>
                {isBasicMoved ? "의견 이동함" : "의견 고정함"}
              </span>
            </div>
            <div className="space-y-2 mt-3.5">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                <p className="text-[9px] text-slate-400 font-extrabold uppercase">1차 투표 (숙의 전)</p>
                <p className="text-xs font-extrabold text-slate-700 mt-1">
                  {firstVote.basicPension === "B-A" && "B-A (균등 월 40만 원)"}
                  {firstVote.basicPension === "B-B" && "B-B (취약 소득 차등)"}
                  {firstVote.basicPension === "B-C" && "B-C (차등 및 60조 기금 적립)"}
                  {firstVote.basicPension === "NONE" && "적합 대안 없음"}
                  {firstVote.basicPension === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
              <div className="p-3 bg-blue-50/30 rounded-xl border border-blue-100">
                <p className="text-[9px] text-blue-500 font-extrabold uppercase">2차 투표 (숙의 후)</p>
                <p className="text-xs font-extrabold text-blue-900 mt-1">
                  {secondVoteResult?.basicPension === "B-A" && "B-A (균등 월 40만 원)"}
                  {secondVoteResult?.basicPension === "B-B" && "B-B (취약 소득 차등)"}
                  {secondVoteResult?.basicPension === "B-C" && "B-C (차등 및 60조 기금 적립)"}
                  {secondVoteResult?.basicPension === "NONE" && "적합 대안 없음"}
                  {secondVoteResult?.basicPension === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
            </div>
          </div>
          <p className="text-[10px] text-slate-500 pt-3 border-t border-slate-100 mt-3 font-semibold">
            확신 점수 변화: {firstVote.basicConfidence}% → {secondVoteResult?.basicConfidence}%
          </p>
        </div>

        {/* 종합 패키지 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center border-b border-slate-100 pb-2.5">
              <h4 className="font-extrabold text-slate-800 text-xs flex items-center gap-1.5 uppercase tracking-wide">
                <Users className="w-4 h-4 text-blue-600" />
                종합 패키지 비교
              </h4>
              <span className={`text-[9px] font-extrabold px-2 py-0.5 rounded ${
                isPackageMoved ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-500"
              }`}>
                {isPackageMoved ? "의견 이동함" : "의견 고정함"}
              </span>
            </div>
            <div className="space-y-2 mt-3.5">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                <p className="text-[9px] text-slate-400 font-extrabold uppercase">1차 투표 (숙의 전)</p>
                <p className="text-xs font-extrabold text-slate-700 mt-1">
                  {firstVote.integratedPackage === "P1" && "P1 (나이유지·보편상향)"}
                  {firstVote.integratedPackage === "P2" && "P2 (나이연장·차등상향)"}
                  {firstVote.integratedPackage === "P3" && "P3 (나이연장·저축대비)"}
                  {firstVote.integratedPackage === "NONE" && "적합 패키지 없음"}
                  {firstVote.integratedPackage === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
              <div className="p-3 bg-blue-50/30 rounded-xl border border-blue-100">
                <p className="text-[9px] text-blue-500 font-extrabold uppercase">2차 투표 (숙의 후)</p>
                <p className="text-xs font-extrabold text-blue-900 mt-1">
                  {secondVoteResult?.integratedPackage === "P1" && "P1 (나이유지·보편상향)"}
                  {secondVoteResult?.integratedPackage === "P2" && "P2 (나이연장·차등상향)"}
                  {secondVoteResult?.integratedPackage === "P3" && "P3 (나이연장·저축대비)"}
                  {secondVoteResult?.integratedPackage === "NONE" && "적합 패키지 없음"}
                  {secondVoteResult?.integratedPackage === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
            </div>
          </div>
          <p className="text-[10px] text-slate-500 pt-3 border-t border-slate-100 mt-3 font-semibold">
            조세 매칭 상태: {isConflictingCombo ? "⚠️ 긴급 재정 충돌 발생" : "✓ 논리 완결 매치 완료"}
          </p>
        </div>
      </div>

      {/* 500명 통계 차트 (3열) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* 국민연금 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3">
          <h4 className="font-extrabold text-slate-800 text-xs flex items-center gap-1.5 uppercase tracking-wide">
            <BarChart2 className="w-4 h-4 text-blue-600" />
            배심원단 국민연금 지지율 변화 (%)
          </h4>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={nationalComparisonData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 8 }} />
                <YAxis tick={{ fontSize: 8 }} />
                <Tooltip formatter={(val) => [`${val}%`, "선호도"]} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <Bar dataKey="first" fill="#94a3b8" name="1차 (숙의 전)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="second" fill="#3b82f6" name="2차 (숙의 후)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[10px] text-slate-550 leading-relaxed pt-2 border-t border-slate-100">
            📊 <strong>분석:</strong> 65세 유지형(N-A)에 안일하게 쏠려 있던 생각들이 고령 인구 부채 현실을 인지하자 68세로 늦추며 기금을 저축하고 적극 운용하려는 든든한 개혁안(N-B, N-C)으로 대거 이동하였습니다.
          </p>
        </div>

        {/* 기초연금 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3">
          <h4 className="font-extrabold text-slate-800 text-xs flex items-center gap-1.5 uppercase tracking-wide">
            <BarChart2 className="w-4 h-4 text-blue-600" />
            배심원단 기초연금 지지율 변화 (%)
          </h4>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={basicComparisonData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 8 }} />
                <YAxis tick={{ fontSize: 8 }} />
                <Tooltip formatter={(val) => [`${val}%`, "선호도"]} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <Bar dataKey="first" fill="#94a3b8" name="1차 (숙의 전)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="second" fill="#f59e0b" name="2차 (숙의 후)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[10px] text-slate-550 leading-relaxed pt-2 border-t border-slate-100">
            📊 <strong>분석:</strong> 모든 어르신께 일괄 40만 원을 주자는 보편 복지(B-A)에서, 취약 노인에게 더 두텁게 주면서 미래 세대를 위해 60조 기금 매칭 저축을 함께 가동하는 실속안(B-C)으로의 선호도 쏠림이 돋보입니다.
          </p>
        </div>

        {/* 종합 패키지 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3">
          <h4 className="font-extrabold text-slate-800 text-xs flex items-center gap-1.5 uppercase tracking-wide">
            <BarChart2 className="w-4 h-4 text-blue-600" />
            배심원단 종합 패키지 비율 변화 (%)
          </h4>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={packageComparisonData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 8 }} />
                <YAxis tick={{ fontSize: 8 }} />
                <Tooltip formatter={(val) => [`${val}%`, "선호도"]} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <Bar dataKey="first" fill="#94a3b8" name="1차 (숙의 전)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="second" fill="#8b5cf6" name="2차 (숙의 후)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[10px] text-slate-550 leading-relaxed pt-2 border-t border-slate-100">
            📊 <strong>분석:</strong> 개별 대안들의 세수 부담 충돌과 장단점을 학습한 결과, 다수의 배심원단이 거시 경제에 가장 유리하며 실효성 높은 P2 및 P3 패키지로 전향하여 숙의 성숙도가 매우 크게 상향되었습니다.
          </p>
        </div>
      </div>

      {/* 가치관 평가 Radar & AI 성숙도 분석 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        
        {/* 가치관 면적 비교 */}
        <div className="lg:col-span-5 bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <h4 className="font-extrabold text-slate-800 text-xs flex items-center gap-1.5 uppercase tracking-wide">
              <Activity className="w-4 h-4 text-blue-600" />
              나의 6개 척도 가치관 성숙 비교 (1~7점)
            </h4>
            <p className="text-[10px] text-slate-400 mt-1">토론 전(회색) vs 토론 후(파란색)의 인지 다이어그램</p>
          </div>
          <div className="h-56 w-full flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="75%" data={valueRadarData}>
                <PolarGrid stroke="#e2e8f0" />
                <PolarAngleAxis dataKey="subject" style={{ fontSize: 8, fontWeight: 600, fill: "#475569" }} />
                <PolarRadiusAxis angle={30} domain={[0, 7]} style={{ fontSize: 7, fill: "#94a3b8" }} />
                <Radar name="1차 (숙의 전)" dataKey="1" stroke="#94a3b8" fill="#94a3b8" fillOpacity={0.2} />
                <Radar name="2차 (숙의 후)" dataKey="2" stroke="#2563eb" fill="#2563eb" fillOpacity={0.4} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[9px] text-slate-450 leading-normal text-center">
            ※ 숙의 과정 후 파란 영역이 고르고 넓게 확장될수록, 연금 개혁의 복잡다단한 가치를 책임감 있게 경청하고 수용했음을 나타냅니다.
          </p>
        </div>

        {/* AI 분석 요약 보고 */}
        <div className="lg:col-span-7 bg-slate-900 text-white p-6 rounded-2xl border border-slate-800 space-y-4 shadow-sm">
          <h4 className="text-xs font-bold text-blue-300 flex items-center gap-1.5 uppercase tracking-wider">
            <Sparkles className="w-4 h-4 text-amber-400" />
            수석 설계사 AI의 나의 의사결정 인지 성숙도 브리핑
          </h4>

          <div className="grid grid-cols-2 gap-4">
            <div className="p-3 bg-slate-800 rounded-xl border border-slate-700">
              <p className="text-[10px] text-slate-400 font-bold uppercase">내 투표 일관성</p>
              <p className="text-xs font-extrabold text-blue-300 mt-1">
                {!isNationalMoved && !isBasicMoved && !isPackageMoved && "초반 확신 유지형 (신념 지향)"}
                {(isNationalMoved || isBasicMoved) && !isPackageMoved && "합리적 선택 조정형 (조화 수용)"}
                {isNationalMoved && isBasicMoved && isPackageMoved && "유연한 사고 전향형 (유연 숙고)"}
                {isPackageMoved && (!isNationalMoved || !isBasicMoved) && "균형 가치 보조형 (논리적 상생)"}
              </p>
            </div>
            <div className="p-3 bg-slate-800 rounded-xl border border-slate-700">
              <p className="text-[10px] text-slate-400 font-bold uppercase">가입 구분</p>
              <p className="text-xs font-extrabold text-blue-300 mt-1">
                {profile.isMember === "yes" ? "국민연금 정회원 납부단" : "미가입 / 피부양 상태 수혜자"}
              </p>
            </div>
          </div>

          <div className="text-xs text-slate-300 leading-relaxed">
            {isConflictingCombo ? (
              <div className="p-4 bg-amber-950/40 border border-amber-900/60 rounded-xl space-y-1.5">
                <p className="font-bold text-amber-300 flex items-center gap-1">
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                  160조 원 재정 갈등 상쇄 조절 진단
                </p>
                <p className="text-[11px] text-slate-300 leading-normal">
                  귀하가 고른 국민연금 N-B(100조)와 기초연금 B-C(60조)는 총합 160조 원에 달하는 대형 적립금이 동시 필요하여 가상 조세 충돌을 빚습니다.
                </p>
                <p className="text-[11px] text-slate-300 leading-normal">
                  이에 대해 귀하는 <strong>
                    {conflictResolution === "opt1" && "국채 발행을 감수하더라도 초기에 공격적으로 저축하여 미래 투자를 도모하는 대담형(옵션 1)"}
                    {conflictResolution === "opt2" && "국민연금 저축 규모를 소폭 감축해 나라 부채를 안정적으로 가다듬으려는 현실형(옵션 2)"}
                    {conflictResolution === "opt3" && "기초연금 초기 저축은 우선 생략하고 선별 차등지급에만 에너지를 몰아주는 선택형(옵션 3)"}
                    {conflictResolution === "opt4" && "연차별로 국비를 유연하게 나누어 상환하며 자녀 충격을 고르게 쪼개는 순차 분할형(옵션 4)"}
                  </strong> 전략을 최종 조절책으로 매칭하셨습니다. 이는 이기적인 선호가 아니라, 국가 살림의 한계점과 미래 청년 세대의 조세 폭탄을 사전에 인지하고 방어책을 자율 구축한 일련의 성숙한 공적 배심 활동임을 정량 증명합니다.
                </p>
              </div>
            ) : (
              <div className="p-4 bg-blue-950/40 border border-blue-900/60 rounded-xl space-y-1.5">
                <p className="font-bold text-blue-300 flex items-center gap-1">
                  <CheckCircle className="w-4 h-4 text-emerald-400" />
                  재정 조화성 및 철학 일관성 진단
                </p>
                <p className="text-[11px] text-slate-300 leading-normal">
                  최종 선택한 개별 대안들의 합이 장기 세수 충돌 없이 매우 깔끔하게 맞아떨어지는 재정 조화 구도를 형성했습니다. 
                </p>
                <p className="text-[11px] text-slate-300 leading-normal">
                  또한 최종 선택하신 종합 패키지 <strong>{secondVoteResult?.integratedPackage === "P1" ? "P1" : secondVoteResult?.integratedPackage === "P2" ? "P2" : "P3"}</strong>와의 논리 구조가 엇박자 없이 동일한 궤적에 정렬되어 있습니다. 이는 자신의 개인 연금 수령 개시일과 국가의 세수 안전망을 조세 갈등 유발 없이 가장 매끄럽게 책임질 수 있는 현명하고 지속가능한 선택 조합을 성취한 것입니다.
                </p>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
