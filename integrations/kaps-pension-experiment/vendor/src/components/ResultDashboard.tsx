import React from "react";
import { VoteData, UserProfile } from "../types";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from "recharts";
import { Award, RefreshCw, BarChart2, CheckCircle, Users, Activity, Sparkles, AlertTriangle } from "lucide-react";

interface ResultDashboardProps {
  profile: UserProfile;
  firstVote: VoteData;
  secondVote: VoteData;
  onRestart: () => void;
}

export default function ResultDashboard({
  profile,
  firstVote,
  secondVote,
  onRestart,
}: ResultDashboardProps) {
  // 가상 대조 참가단 500명의 숙의실험 전후 통계 모델 데이터
  // 국민연금 전후 통계
  const nationalComparisonData = [
    { name: "N-A (65세유지·세금)", first: 45, second: 30 },
    { name: "N-B (68세·저축)", first: 25, second: 35 },
    { name: "N-C (68세·투자)", first: 15, second: 27 },
    { name: "유보/기타", first: 15, second: 8 },
  ];

  // 기초연금 전후 통계
  const basicComparisonData = [
    { name: "B-A (골고루 40만)", first: 50, second: 35 },
    { name: "B-B (차등 지급)", first: 30, second: 31 },
    { name: "B-C (차등+저축)", first: 10, second: 28 },
    { name: "유보/기타", first: 10, second: 6 },
  ];

  // 통합 패키지 전후 통계
  const packageComparisonData = [
    { name: "P1 (보편유지)", first: 48, second: 33 },
    { name: "P2 (차등보장)", first: 28, second: 36 },
    { name: "P3 (투자저축)", first: 12, second: 25 },
    { name: "유보/기타", first: 12, second: 6 },
  ];

  // 가치관 수용성 레이더 차트 데이터
  const valueRadarData = [
    { subject: "정부안 호감도", 1: firstVote.acceptAsGovernment, 2: secondVote.acceptAsGovernment, fullMark: 7 },
    { subject: "사회적 배려심", 1: firstVote.acceptForSociety, 2: secondVote.acceptForSociety, fullMark: 7 },
    { subject: "세대간 공평성", 1: firstVote.generationalFairness, 2: secondVote.generationalFairness, fullMark: 7 },
    { subject: "취약 노인 지원", 1: firstVote.poorProtection, 2: secondVote.poorProtection, fullMark: 7 },
    { subject: "연금의 지속성", 1: firstVote.sustainability, 2: secondVote.sustainability, fullMark: 7 },
    { subject: "투자의 모험성", 1: firstVote.riskManageable, 2: secondVote.riskManageable, fullMark: 7 },
  ];

  // 선택 이동 여부 진단
  const isNationalMoved = firstVote.nationalPension !== secondVote.nationalPension;
  const isBasicMoved = firstVote.basicPension !== secondVote.basicPension;
  const isPackageMoved = firstVote.integratedPackage !== secondVote.integratedPackage;

  // 일치도/불일치도 분석
  const isConflictingCombo = firstVote.nationalPension === "N-B" && firstVote.basicPension === "B-C";
  const selectedConflictRes = secondVote.conflictResolution || "opt4";

  return (
    <div className="space-y-8 animate-fade-in" id="result-dashboard-wrapper">
      {/* 최상단 리포트 카드 */}
      <div className="bg-gradient-to-br from-indigo-950 via-slate-900 to-indigo-900 text-white p-6 md:p-8 rounded-2xl shadow-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-1.5 bg-indigo-500/20 text-indigo-300 text-xs font-bold px-3 py-1 rounded-full border border-indigo-500/20">
            <Award className="w-4 h-4 text-amber-400" />
            <span>AI 숙의실험 분석 보고서</span>
          </div>
          <h2 className="text-xl md:text-3xl font-extrabold tracking-tight mt-1">연금개혁 나의 1·2차 투표 결과 보고서</h2>
          <p className="text-xs md:text-sm text-slate-300 mt-1 leading-relaxed">
            내가 공부하고 토론하기 전(1차)과 후(2차)에 투표한 결과와 다른 가상 참가자 500명의 생각을 비교해 보여주는 종합 분석 리포트입니다.
          </p>
        </div>
        <button
          id="btn-restart-simulator"
          onClick={onRestart}
          className="flex items-center gap-2 px-5 py-3.5 bg-indigo-600 hover:bg-indigo-700 hover:scale-[1.02] active:scale-[0.98] transition-all font-bold rounded-xl text-xs md:text-sm shadow cursor-pointer text-white"
        >
          <RefreshCw className="w-4 h-4" />
          처음부터 다시 시작하기
        </button>
      </div>

      {/* 개인 의사결정 추적 (1차 vs 2차 투표) Bento Grid 1 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* 국민연금 매칭 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-4 flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center border-b border-slate-100 pb-2.5">
              <h3 className="font-bold text-slate-800 text-xs md:text-sm flex items-center gap-1.5 uppercase tracking-wide">
                <Users className="w-4 h-4 text-indigo-600" />
                내 국민연금 생각 변화
              </h3>
              <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-md ${
                isNationalMoved ? "bg-amber-100 text-amber-800" : "bg-slate-150 text-slate-600"
              }`}>
                {isNationalMoved ? "생각이 바뀌었어요" : "생각을 유지했어요"}
              </span>
            </div>
            <div className="space-y-2 mt-3.5">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">토론하기 전 (1차 투표)</p>
                <p className="text-xs md:text-sm font-extrabold text-slate-700 mt-1">
                  {firstVote.nationalPension === "N-A" && "N-A: 만 65세 유지 및 국가 세금 지원"}
                  {firstVote.nationalPension === "N-B" && "N-B: 만 68세로 늦추고 돈 저축하기"}
                  {firstVote.nationalPension === "N-C" && "N-C: 만 68세로 늦추고 적극적 투자하기"}
                  {firstVote.nationalPension === "NONE" && "지지하는 대안 없음"}
                  {firstVote.nationalPension === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
              <div className="p-3 bg-indigo-50/30 rounded-xl border border-indigo-100">
                <p className="text-[10px] text-indigo-500 font-bold uppercase tracking-wider">토론하고 난 후 (2차 최종 투표)</p>
                <p className="text-xs md:text-sm font-extrabold text-indigo-900 mt-1">
                  {secondVote.nationalPension === "N-A" && "N-A: 만 65세 유지 및 국가 세금 지원"}
                  {secondVote.nationalPension === "N-B" && "N-B: 만 68세로 늦추고 돈 저축하기"}
                  {secondVote.nationalPension === "N-C" && "N-C: 만 68세로 늦추고 적극적 투자하기"}
                  {secondVote.nationalPension === "NONE" && "지지하는 대안 없음"}
                  {secondVote.nationalPension === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
            </div>
          </div>
          <p className="text-[11px] text-slate-500 leading-tight pt-2 border-t border-slate-100 mt-2">
            <strong>내 선택의 확신 점수 변화:</strong> {firstVote.nationalConfidence}% → {secondVote.nationalConfidence}% (편차: {secondVote.nationalConfidence - firstVote.nationalConfidence}%)
          </p>
        </div>

        {/* 기초연금 매칭 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-4 flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center border-b border-slate-100 pb-2.5">
              <h3 className="font-bold text-slate-800 text-xs md:text-sm flex items-center gap-1.5 uppercase tracking-wide">
                <Users className="w-4 h-4 text-indigo-600" />
                내 기초연금 생각 변화
              </h3>
              <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-md ${
                isBasicMoved ? "bg-amber-100 text-amber-800" : "bg-slate-150 text-slate-600"
              }`}>
                {isBasicMoved ? "생각이 바뀌었어요" : "생각을 유지했어요"}
              </span>
            </div>
            <div className="space-y-2 mt-3.5">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">토론하기 전 (1차 투표)</p>
                <p className="text-xs md:text-sm font-extrabold text-slate-700 mt-1">
                  {firstVote.basicPension === "B-A" && "B-A: 소득 하위 70% 어르신께 월 40만 원"}
                  {firstVote.basicPension === "B-B" && "B-B: 어려운 분께 더 많이 주는 차등 지급"}
                  {firstVote.basicPension === "B-C" && "B-C: 차등 지급하고 세금 아끼게 미리 저축하기"}
                  {firstVote.basicPension === "NONE" && "지지하는 대안 없음"}
                  {firstVote.basicPension === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
              <div className="p-3 bg-indigo-50/30 rounded-xl border border-indigo-100">
                <p className="text-[10px] text-indigo-500 font-bold uppercase tracking-wider">토론하고 난 후 (2차 최종 투표)</p>
                <p className="text-xs md:text-sm font-extrabold text-indigo-900 mt-1">
                  {secondVote.basicPension === "B-A" && "B-A: 소득 하위 70% 어르신께 월 40만 원"}
                  {secondVote.basicPension === "B-B" && "B-B: 어려운 분께 더 많이 주는 차등 지급"}
                  {secondVote.basicPension === "B-C" && "B-C: 차등 지급하고 세금 아끼게 미리 저축하기"}
                  {secondVote.basicPension === "NONE" && "지지하는 대안 없음"}
                  {secondVote.basicPension === "UNDECIDED" && "판단 보류 / 유보"}
                </p>
              </div>
            </div>
          </div>
          <p className="text-[11px] text-slate-500 leading-tight pt-2 border-t border-slate-100 mt-2">
            <strong>내 선택의 확신 점수 변화:</strong> {firstVote.basicConfidence}% → {secondVote.basicConfidence}% (편차: {secondVote.basicConfidence - firstVote.basicConfidence}%)
          </p>
        </div>

        {/* 통합 패키지 매칭 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-4 flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center border-b border-slate-100 pb-2.5">
              <h3 className="font-bold text-slate-800 text-xs md:text-sm flex items-center gap-1.5 uppercase tracking-wide">
                <Users className="w-4 h-4 text-indigo-600" />
                내 종합 패키지 생각 변화
              </h3>
              <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-md ${
                isPackageMoved ? "bg-amber-100 text-amber-800" : "bg-slate-150 text-slate-600"
              }`}>
                {isPackageMoved ? "생각이 바뀌었어요" : "생각을 유지했어요"}
              </span>
            </div>
            <div className="space-y-2 mt-3.5">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">토론하기 전 (1차 투표)</p>
                <p className="text-xs md:text-sm font-extrabold text-slate-700 mt-1">
                  {firstVote.integratedPackage === "P1" && "P1: 만 65세 유지 및 어르신 골고루 상향"}
                  {firstVote.integratedPackage === "P2" && "P2: 만 68세 연장 및 어려운 어르신 집중 지원"}
                  {firstVote.integratedPackage === "P3" && "P3: 만 68세 연장 및 저축과 기금 적극 투자"}
                  {firstVote.integratedPackage === "NONE" && "어울리는 패키지 없음"}
                  {firstVote.integratedPackage === "UNDECIDED" && "아직 판단을 미룸"}
                </p>
              </div>
              <div className="p-3 bg-indigo-50/30 rounded-xl border border-indigo-100">
                <p className="text-[10px] text-indigo-500 font-bold uppercase tracking-wider">토론하고 난 후 (2차 최종 투표)</p>
                <p className="text-xs md:text-sm font-extrabold text-indigo-900 mt-1">
                  {secondVote.integratedPackage === "P1" && "P1: 만 65세 유지 및 어르신 골고루 상향"}
                  {secondVote.integratedPackage === "P2" && "P2: 만 68세 연장 및 어려운 어르신 집중 지원"}
                  {secondVote.integratedPackage === "P3" && "P3: 만 68세 연장 및 저축과 기금 적극 투자"}
                  {secondVote.integratedPackage === "NONE" && "어울리는 패키지 없음"}
                  {secondVote.integratedPackage === "UNDECIDED" && "아직 판단을 미룸"}
                </p>
              </div>
            </div>
          </div>
          <p className="text-[11px] text-slate-500 leading-tight pt-2 border-t border-slate-100 mt-2 font-semibold">
            <strong>나의 가입 구분:</strong> {profile.isMember === "yes" ? "국민연금 가입 회원" : "미가입 또는 피부양자 상태"}
          </p>
        </div>
      </div>

      {/* 500명 가상 실험 참여단의 숙의 이동 추이 시각화 (Recharts) Bento Grid 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* 국민연금 전후 통계 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-4">
          <div>
            <h3 className="font-bold text-slate-800 text-xs md:text-sm flex items-center gap-1.5 uppercase tracking-wide">
              <BarChart2 className="w-4 h-4 text-indigo-600" />
              참가자단 국민연금 선택 비율 변화 (%)
            </h3>
            <p className="text-[11px] text-slate-400">500명의 숙의전(1차) vs 숙의후(2차) 통계</p>
          </div>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={nationalComparisonData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 9 }} />
                <YAxis tick={{ fontSize: 9 }} />
                <Tooltip formatter={(value) => [`${value}%`, "의견 점유율"]} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                <Bar dataKey="first" fill="#94a3b8" name="1차 (숙의 전)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="second" fill="#4f46e5" name="2차 (숙의 후)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[11px] text-slate-600 leading-relaxed pt-2 border-t border-slate-100">
            📊 <strong>분석:</strong> 나라 재정 상황을 꼼꼼히 배우고 토론하면서, 연금 기금을 오래 지키기 위해 받는 나이를 조금 늦추더라도 저축과 투자를 확대하는 방향(N-B, N-C 안)으로 참가자들의 의견이 많이 이동했습니다.
          </p>
        </div>

        {/* 기초연금 전후 통계 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-4">
          <div>
            <h3 className="font-bold text-slate-800 text-xs md:text-sm flex items-center gap-1.5 uppercase tracking-wide">
              <BarChart2 className="w-4 h-4 text-indigo-600" />
              참가자단 기초연금 선택 비율 변화 (%)
            </h3>
            <p className="text-[11px] text-slate-400">500명의 숙의전(1차) vs 숙의후(2차) 통계</p>
          </div>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={basicComparisonData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 9 }} />
                <YAxis tick={{ fontSize: 9 }} />
                <Tooltip formatter={(value) => [`${value}%`, "의견 점유율"]} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                <Bar dataKey="first" fill="#94a3b8" name="1차 (숙의 전)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="second" fill="#f59e0b" name="2차 (숙의 후)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[11px] text-slate-600 leading-relaxed pt-2 border-t border-slate-100">
            📊 <strong>분석:</strong> 형편이 어려운 어르신들을 집중해서 지원하는 동시에, 미래 세대의 세금 부담을 덜 수 있게 미리 돈을 저축해 놓자는 방안(B-C 안)으로 지지도가 크게 증가했습니다.
          </p>
        </div>

        {/* 통합 패키지 전후 통계 */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-4">
          <div>
            <h3 className="font-bold text-slate-800 text-xs md:text-sm flex items-center gap-1.5 uppercase tracking-wide">
              <BarChart2 className="w-4 h-4 text-indigo-600" />
              참가자단 통합 패키지 변화율 (%)
            </h3>
            <p className="text-[11px] text-slate-400">500명의 숙의전(1차) vs 숙의후(2차) 통계</p>
          </div>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={packageComparisonData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 9 }} />
                <YAxis tick={{ fontSize: 9 }} />
                <Tooltip formatter={(value) => [`${value}%`, "의견 점유율"]} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                <Bar dataKey="first" fill="#94a3b8" name="1차 (숙의 전)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="second" fill="#6366f1" name="2차 (숙의 후)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[11px] text-slate-600 leading-relaxed pt-2 border-t border-slate-100">
            📊 <strong>분석:</strong> 개별 연금뿐만 아니라 나라 전체 예산과 미래 세금 부담을 패키지로 한눈에 보면서 조율하다 보니, 보다 실현 가능한 P2, P3 패키지로 의견이 모아지는 흐름이 뚜렷했습니다.
          </p>
        </div>
      </div>

      {/* 가치관 변천 다차원 평가 (레이더 차트) & 정량 지표 Bento Grid 3 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* 레이더 차트 (5 cols) */}
        <div className="lg:col-span-5 bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <h3 className="font-bold text-slate-800 text-xs md:text-sm flex items-center gap-1.5 uppercase tracking-wide">
              <Activity className="w-4 h-4 text-indigo-600" />
              연금에 대한 나의 가치관 변화 비교 (1~7점)
            </h3>
            <p className="text-[11px] text-slate-400">토론 전(회색)과 토론 후(보라색)의 생각 면적 변화</p>
          </div>
          <div className="h-56 w-full flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="75%" data={valueRadarData}>
                <PolarGrid stroke="#e2e8f0" />
                <PolarAngleAxis dataKey="subject" style={{ fontSize: 9, fontWeight: 600, fill: "#475569" }} />
                <PolarRadiusAxis angle={30} domain={[0, 7]} style={{ fontSize: 8, fill: "#94a3b8" }} />
                <Radar name="1차 (숙의 전)" dataKey="1" stroke="#94a3b8" fill="#94a3b8" fillOpacity={0.2} />
                <Radar name="2차 (숙의 후)" dataKey="2" stroke="#6366f1" fill="#6366f1" fillOpacity={0.4} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[10px] text-slate-450 text-center leading-relaxed">
            ※ 선의 면적이 넓고 고르게 펼쳐질수록, 연금 개혁의 복잡한 세금 및 형평성 가치들을 균형 있게 수용하고 있음을 뜻합니다.
          </p>
        </div>

        {/* 정량 숙의 성숙도 분석 및 정성 분석 (7 cols) */}
        <div className="lg:col-span-7 space-y-6">
          <div className="bg-slate-900 text-white p-5 rounded-2xl space-y-4 border border-slate-800 shadow-md">
            <h3 className="text-xs md:text-sm font-bold flex items-center gap-2 text-indigo-300 uppercase tracking-wider">
              <Sparkles className="w-5 h-5 text-amber-400" />
              AI 연금 설계사가 분석한 나의 최종 의견 요약
            </h3>

            <div className="grid grid-cols-2 gap-4">
              <div className="p-3.5 bg-slate-800/80 rounded-xl border border-slate-700/60">
                <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">내 투표의 일관성</p>
                <p className="text-sm md:text-base font-extrabold text-indigo-300 mt-1.5">
                  {!isNationalMoved && !isBasicMoved && !isPackageMoved ? "높음 (처음 생각을 확고하게 유지)" : ""}
                  {(isNationalMoved || isBasicMoved) && !isPackageMoved ? "보통 (고민 끝에 일부 의견을 조정)" : ""}
                  {isNationalMoved && isBasicMoved && isPackageMoved ? "유연함 (토론 후 완전히 새로운 시각 획득)" : ""}
                  {isPackageMoved && (!isNationalMoved || !isBasicMoved) ? "균형적 (패키지와 개별안을 꼼꼼하게 조율)" : ""}
                </p>
              </div>

              <div className="p-3.5 bg-slate-800/80 rounded-xl border border-slate-700/60">
                <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">생각의 확정 여부</p>
                <p className="text-sm md:text-base font-extrabold text-indigo-300 mt-1.5">
                  {firstVote.nationalPension === "UNDECIDED" && secondVote.nationalPension !== "UNDECIDED" ? "유보에서 마음의 결정 완료" : "처음부터 끝까지 뚜렷하게 결정"}
                </p>
              </div>
            </div>

            <div className="text-xs text-slate-300 leading-relaxed space-y-2">
              {/* 개별안-통합안 불일치 분석 브리핑 */}
              {isConflictingCombo ? (
                <div className="p-4 bg-rose-950/40 border border-rose-900/60 rounded-xl leading-relaxed animate-fade-in">
                  <p className="font-bold text-rose-300 flex items-center gap-1.5">
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                    [160조 원 재정 충돌 해결 방안 분석]
                  </p>
                  <p className="text-[11px] text-rose-200 mt-1.5">
                    내가 선택한 개별 계획들은 국민연금 저축(N-B 100조)과 기초연금 저축(B-C 60조)을 합쳐 한 번에 큰돈(160조)을 모아야 하는 초대형 재정 조합입니다.
                  </p>
                  <p className="text-[11px] text-rose-200 mt-1">
                    이에 대해 귀하는 <strong>
                      {selectedConflictRes === "opt1" && "초반에 160조 국채를 발행해서라도 과감하게 저축해 투자 수익을 내겠다는 공격적인 해결 방식(옵션 1)"}
                      {selectedConflictRes === "opt2" && "국민연금 저축을 조금 줄여 국가 빚을 안정적으로 조절하겠다는 절제된 방식(옵션 2)"}
                      {selectedConflictRes === "opt3" && "기초연금 저축 규모를 줄여 당장 충돌하는 예산 압박을 낮추려는 방식(옵션 3)"}
                      {selectedConflictRes === "opt4" && "저축을 4~5년에 걸쳐 부드럽게 나누어 내며 나라 경제의 충격을 줄이려는 합리적인 조율 방식(옵션 4)"}
                      {selectedConflictRes === "opt5" && "예산 불일치 골치 아픈 문제를 피하기 위해, 처음부터 꽉 짜인 종합 패키지 대안으로 돌아가는 안전한 방식(옵션 5)"}
                    </strong>을 완화 조치로 고르셨습니다. 
                    이는 단순히 좋은 제도를 고르는 데 그치지 않고, 현실적인 나라 살림 걱정과 세금 딜레마를 함께 인지하여 균형 있게 조율해 낸 훌륭하고 책임감 있는 대화 결과입니다.
                  </p>
                </div>
              ) : (
                <div className="p-4 bg-indigo-950/40 border border-indigo-900/60 rounded-xl leading-relaxed animate-fade-in">
                  <p className="font-bold text-indigo-300 flex items-center gap-1.5">
                    <CheckCircle className="w-4 h-4 text-emerald-400" />
                    [재정 매칭 및 논리 일관성 분석]
                  </p>
                  <p className="text-[11px] text-indigo-200 mt-1.5">
                    내가 최종 선택한 국민연금과 기초연금 개별 대안들은 나라 예산 조달이나 저축 규모 면에서 대규모의 자금 충돌을 유발하지 않고 아주 매끄럽고 건강하게 어우러지는 튼튼한 호환 구조를 보이고 있습니다.
                  </p>
                  <p className="text-[11px] text-indigo-200 mt-1">
                    또한, 종합 패키지로 <strong>{secondVote.integratedPackage === "P1" ? "P1 (나이유지·보편상향)" : secondVote.integratedPackage === "P2" ? "P2 (나이연장·차등상향)" : "P3 (나이연장·저축대비)"}</strong>안을 함께 선택해 주심으로써 생각의 철학이 매우 논리적이고 일관되게 연결되어 있음을 보여주셨습니다. 이는 내 지갑 속 미래 가처분 소득과 우리 사회 어르신들의 노후 보장이라는 두 마리 토끼를 매우 슬기롭게 조율해 낸 뛰어난 결정입니다.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
