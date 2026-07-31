import React, { useState } from "react";
import { VoteData, NationalOption, BasicOption, IntegratedOption } from "../types";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  AreaChart,
  Area,
} from "recharts";
import {
  Users,
  AlertTriangle,
  Landmark,
  Shield,
  Wallet,
  Check,
  TrendingUp,
  HelpCircle,
  Vote,
  Sparkles,
  ArrowRight,
} from "lucide-react";

interface ReformBoardProps {
  voteData: VoteData;
  setVoteData: (data: VoteData) => void;
  onComplete: (data: VoteData) => void;
}

export default function ReformBoard({ voteData, setVoteData, onComplete }: ReformBoardProps) {
  // Factsheet Tab: 'population' | 'fund' | 'poverty'
  const [factTab, setFactTab] = useState<"population" | "fund" | "poverty">("population");
  
  // Package tabs: 'national' | 'basic' | 'package'
  const [propTab, setPropTab] = useState<"national" | "basic" | "package">("national");

  // Recharts Data
  const populationData = [
    { year: 2020, ratio: 15.7, support: 21.8 },
    { year: 2030, ratio: 25.5, support: 38.6 },
    { year: 2040, ratio: 34.4, support: 60.5 },
    { year: 2050, ratio: 40.1, support: 78.9 },
    { year: 2060, ratio: 43.8, support: 92.4 },
    { year: 2070, ratio: 46.4, support: 104.2 },
  ];

  const fundTrendData = [
    { year: 2025, fund: 1100 },
    { year: 2030, fund: 1450 },
    { year: 2040, fund: 1750 },
    { year: 2048, fund: 1500 },
    { year: 2055, fund: 950 },
    { year: 2065, fund: 0 },
    { year: 2070, fund: -600 },
  ];

  const nationalOptions = [
    { value: "N-A", label: "N-A 안 (65세 유지형)", desc: "⏱️ 수급 만 65세 유지 / 매년 국가 총소득(GDP)의 0.6% 세금 추가 매칭 (연간 약 18조 원 수준)" },
    { value: "N-B", label: "N-B 안 (세금 아끼기형)", desc: "⏱️ 수급 만 68세로 연기 / 초반 2년 국고 100조 원 선제 저축 / 매년 보탤 세금은 연 7.5조 원으로 절감" },
    { value: "N-C", label: "N-C 안 (고수익 투자형)", desc: "⏱️ 수급 만 68세로 연기 / 연 6.0% 적극적 공격형 고수익 추진 / 비상 상황 전까지는 국가 재정 세금 수입 0원" },
    { value: "NONE", label: "마음에 드는 안이 없습니다", desc: "제시된 세 가지 국민연금안 모두 지지하지 않습니다." },
  ];

  const basicOptions = [
    { value: "B-A", label: "B-A 안 (모두 똑같이 받기)", desc: "💰 소득 수준과 관계없이 전 대상자에게 월 40만 원 똑같이 분배 (매년 들어갈 세금이 고루 늘어남)" },
    { value: "B-B", label: "B-B 안 (어려운 분 집중형)", desc: "💰 소득에 따라 차등 지급 (하위 월 50만 원 / 중위 월 35만 원 / 상위 월 20만 원)" },
    { value: "B-C", label: "B-C 안 (기초연금 미래대비형)", desc: "💰 월 20만~50만 차등 지급 + 초반 2년 세금 60조 원을 모아 저축 / 정부 세금 수혈 한도를 연 50조 상한선으로 조절" },
    { value: "NONE", label: "마음에 드는 안이 없습니다", desc: "제시된 기초연금 대안 모두 지지하지 않습니다." },
  ];

  const integratedPackages = [
    { value: "P1", label: "패키지 P1 (나이 유지 + 골고루 분배)", desc: "국민연금 65세 유지(N-A) + 기초연금 균등 40만 원(B-A). 가장 직관적이나 미래 후손들의 평생 세금 폭탄 증가." },
    { value: "P2", label: "패키지 P2 (세대 분담 + 가난한 분 집중)", desc: "국민연금 68세 연기/100조 저축(N-B) + 기초연금 차등(B-B). 가난한 어르신께 국가 복지 집중, 미래 세대와 짐 나눔." },
    { value: "P3", label: "패키지 P3 (스마트 투자 + 국가 재정 상한)", desc: "국민연금 6.0% 고수익 추진(N-C) + 기초연금 60조 기금 저축(B-C). 선제적 금융 기금 축적으로 지출 효율 최대화." },
    { value: "NONE", label: "마음에 드는 패키지가 없습니다", desc: "세 개 패키지 대안 중 제 가치관과 부합하는 계획이 없습니다." },
  ];

  const reasons = [
    { value: "age", label: "지급 시작 연령" },
    { value: "tax", label: "국민 세금(국고) 부담" },
    { value: "risk", label: "투자 자산 리스크" },
    { value: "sustainability", label: "연금 지속성" },
    { value: "future_generation", label: "미래 청년부담" },
    { value: "stability", label: "노후 생계안정" },
  ];

  // Check fiscal mismatch (N-B + B-C chosen simultaneously requires 160 Trillion KRW early tax savings)
  const isConflict = voteData.nationalPension === "N-B" && voteData.basicPension === "B-C";

  const changeVote = (field: keyof VoteData, value: any) => {
    setVoteData({ ...voteData, [field]: value });
  };

  const handleNext = () => {
    onComplete(voteData);
  };

  const checkValidation = () => {
    const nationalFilled = voteData.nationalPension !== "";
    const basicFilled = voteData.basicPension !== "";
    const packageFilled = voteData.integratedPackage !== "";
    
    // If conflict detected, user must choose a conflict resolution option
    const conflictResolved = isConflict ? !!voteData.conflictResolution : true;

    // Check optional sub-questions if chosen standard plan
    const nationalReasonFilled = (voteData.nationalPension !== "NONE" && voteData.nationalPension !== "") 
      ? voteData.nationalReason !== "" 
      : true;

    return nationalFilled && basicFilled && packageFilled && conflictResolved && nationalReasonFilled;
  };

  return (
    <div className="space-y-6 animate-fade-in" id="reform-board-container">
      {/* 마스터 보드 2열 그리드 레이아웃 */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        
        {/* 왼쪽 열: 인구/재정 팩트시트 고지서 (40% 공간) */}
        <div className="xl:col-span-5 space-y-6">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            {/* 고지서 헤더 */}
            <div className="bg-slate-900 text-white p-6">
              <span className="text-[10px] font-extrabold tracking-wider bg-red-600 px-2.5 py-1 rounded-full uppercase font-mono">
                FACT REPORT
              </span>
              <h3 className="text-lg font-extrabold tracking-tight text-white mt-2">
                대한민국 초고령화와 공적연금 실태 고지서
              </h3>
              <p className="text-xs text-slate-300 mt-1">
                통계청 공식 전망과 연구진 재정 추계를 바탕으로 재정 상태와 시급성을 투명하게 공시합니다.
              </p>
            </div>

            {/* 팩트시트 탭 */}
            <div className="flex border-b border-slate-200 bg-slate-50">
              <button
                id="tab-fact-population"
                onClick={() => setFactTab("population")}
                className={`flex-1 py-3 text-center text-xs font-bold transition-all border-b-2 flex items-center justify-center gap-1.5 ${
                  factTab === "population"
                    ? "border-blue-600 text-blue-700 bg-white"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                <Users className="w-3.5 h-3.5" />
                인구고령화
              </button>
              <button
                id="tab-fact-fund"
                onClick={() => setFactTab("fund")}
                className={`flex-1 py-3 text-center text-xs font-bold transition-all border-b-2 flex items-center justify-center gap-1.5 ${
                  factTab === "fund"
                    ? "border-blue-600 text-blue-700 bg-white"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                기금 고갈선
              </button>
              <button
                id="tab-fact-poverty"
                onClick={() => setFactTab("poverty")}
                className={`flex-1 py-3 text-center text-xs font-bold transition-all border-b-2 flex items-center justify-center gap-1.5 ${
                  factTab === "poverty"
                    ? "border-blue-600 text-blue-700 bg-white"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                <Landmark className="w-3.5 h-3.5" />
                노인빈곤 & 세금
              </button>
            </div>

            <div className="p-6 space-y-4">
              {/* 탭 1: 인구고령화 */}
              {factTab === "population" && (
                <div className="space-y-4 animate-fade-in" id="fact-panel-population">
                  <div className="bg-blue-50/50 border border-blue-100 p-4 rounded-xl">
                    <p className="text-xs text-blue-900 font-extrabold flex items-center gap-1">
                      <TrendingUp className="w-4 h-4 text-blue-600" />
                      일하는 청년 1명이 어르신 1명을 온전히 혼자 부양
                    </p>
                    <p className="text-[11px] text-slate-600 mt-1 leading-relaxed">
                      현재 노인 인구 비율은 15.7%이지만 은퇴 예정자들이 늘면서 2070년에는 <strong>46.4%</strong>에 달해 사회의 절반이 노인이 됩니다.
                    </p>
                  </div>

                  {/* 차트 시각화 */}
                  <div className="h-44 w-full bg-slate-50/50 p-2 rounded-xl border border-slate-200">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={populationData} margin={{ top: 5, right: 10, left: -25, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="year" tick={{ fontSize: 9 }} />
                        <YAxis tick={{ fontSize: 9 }} />
                        <Tooltip contentStyle={{ fontSize: 10 }} />
                        <Line type="monotone" dataKey="ratio" stroke="#2563eb" strokeWidth={2.5} name="65세이상 비율(%)" />
                        <Line type="monotone" dataKey="support" stroke="#dc2626" strokeWidth={2.5} name="노년부양비(명)" />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>

                  {/* 미니 테이블 */}
                  <div className="overflow-hidden rounded-lg border border-slate-200 text-[11px]">
                    <div className="grid grid-cols-3 bg-slate-50 font-bold p-2 border-b text-slate-700">
                      <span>비교 지표</span>
                      <span className="text-right">현재수준</span>
                      <span className="text-right text-red-600">미래전망(2070)</span>
                    </div>
                    <div className="grid grid-cols-3 p-2 border-b text-slate-600">
                      <span>65세 이상 비율</span>
                      <span className="text-right">15.7%</span>
                      <span className="text-right font-semibold text-red-600">46.4%</span>
                    </div>
                    <div className="grid grid-cols-3 p-2 text-slate-600">
                      <span>청년 대비 어르신</span>
                      <span className="text-right">4명당 1명</span>
                      <span className="text-right font-semibold text-red-600 font-mono">1명당 1명 이상</span>
                    </div>
                  </div>
                </div>
              )}

              {/* 탭 2: 기금고갈 */}
              {factTab === "fund" && (
                <div className="space-y-4 animate-fade-in" id="fact-panel-fund">
                  <div className="bg-red-50 border border-red-100 p-4 rounded-xl">
                    <p className="text-xs text-red-900 font-extrabold flex items-center gap-1">
                      <AlertTriangle className="w-4 h-4 text-red-600" />
                      아무 대책이 없다면 2065년 연금 금고 '완기 고갈'
                    </p>
                    <p className="text-[11px] text-slate-600 mt-1 leading-relaxed">
                      국민연금 보험료 9% 수치 그대로 방치할 경우, 2048년 자산 성장이 정점을 찍은 후 <strong>2065년에 완기 바닥</strong>이 나 잔액은 마이너스로 돌아서게 됩니다.
                    </p>
                  </div>

                  {/* 차트 시각화 */}
                  <div className="h-44 w-full bg-slate-50/50 p-2 rounded-xl border border-slate-200">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={fundTrendData} margin={{ top: 5, right: 10, left: -25, bottom: 0 }}>
                        <defs>
                          <linearGradient id="fundGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#dc2626" stopOpacity={0.2}/>
                            <stop offset="95%" stopColor="#dc2626" stopOpacity={0}/>
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="year" tick={{ fontSize: 9 }} />
                        <YAxis tick={{ fontSize: 9 }} />
                        <Tooltip contentStyle={{ fontSize: 10 }} />
                        <Area type="monotone" dataKey="fund" stroke="#dc2626" strokeWidth={2.5} fill="url(#fundGrad)" name="적립금 잔고(조원)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>

                  <p className="text-[10px] text-slate-450 leading-relaxed">
                    ※ 고갈 직후(2079년 이후) 그해 은퇴 어르신 연금액 지급을 위해 청년들은 <strong>월급의 39.2%</strong>를 세금/보험료로 다 쏟아부어야 합니다.
                  </p>
                </div>
              )}

              {/* 탭 3: 빈곤 & 세금 */}
              {factTab === "poverty" && (
                <div className="space-y-4 animate-fade-in" id="fact-panel-poverty">
                  <div className="bg-amber-50 border border-amber-100 p-4 rounded-xl space-y-3">
                    <p className="text-xs text-amber-950 font-extrabold flex items-center gap-1.5">
                      <Landmark className="w-4 h-4 text-amber-600" />
                      OECD 노인 빈곤율 부동의 압도적 1위 (35.9%)
                    </p>
                    <p className="text-[11px] text-slate-650 leading-relaxed">
                      은퇴 노인 10명 중 3.5명은 소득 최하 수준에 시달려 기초 보장망(기초연금) 확대가 필수적입니다. 하지만 기초연금 재원은 순수 100% <strong>세금</strong>으로 조달됩니다.
                    </p>
                  </div>

                  <div className="p-4 bg-slate-50/80 rounded-xl border border-slate-200 text-xs text-slate-600 space-y-2.5">
                    <p className="font-semibold text-slate-800">💡 핵심 가치 저울질 포인트:</p>
                    <ul className="space-y-1.5 list-disc list-inside text-[11px] leading-relaxed">
                      <li><strong>보편 복지론:</strong> 모두 공평하게 40만 원씩 골고루 타는 것이 타당한가?</li>
                      <li><strong>선택 집중론:</strong> 부유한 노인은 줄이고 어려운 분께 50만 원 집중 지원하는 게 맞는가?</li>
                      <li><strong>세대 배려론:</strong> 세수 감당을 위해 60조 원 기금 저축 제도를 선제 도입해 상한 캡을 씌워야 하는가?</li>
                    </ul>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 대안 요약 설명 카드 */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="border-b border-slate-100 p-5 bg-slate-50/50 flex justify-between items-center">
              <h4 className="text-xs font-extrabold text-slate-600 tracking-wider uppercase flex items-center gap-1">
                <Sparkles className="w-3.5 h-3.5 text-blue-600" />
                개혁 대안 핵심 비교
              </h4>
              <div className="flex gap-1">
                {["national", "basic", "package"].map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setPropTab(tab as any)}
                    className={`px-2.5 py-1 text-[10px] font-bold rounded-lg transition-all ${
                      propTab === tab
                        ? "bg-slate-900 text-white"
                        : "bg-slate-200/60 text-slate-600 hover:bg-slate-200"
                    }`}
                  >
                    {tab === "national" ? "국민연금" : tab === "basic" ? "기초연금" : "통합패키지"}
                  </button>
                ))}
              </div>
            </div>

            <div className="p-5 max-h-[300px] overflow-y-auto custom-scrollbar">
              {propTab === "national" && (
                <div className="space-y-3 animate-fade-in">
                  <div className="p-3 bg-blue-50/30 rounded-xl border border-slate-100">
                    <p className="text-xs font-bold text-slate-800">N-A 안: 65세 수급형</p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">나이 연장 고통은 없으나, 매년 우리나라 총 소득(GDP)의 0.6% 세금을 지원하여 매칭해야 함 (자녀의 미래 세금 상승)</p>
                  </div>
                  <div className="p-3 bg-blue-50/30 rounded-xl border border-slate-100">
                    <p className="text-xs font-bold text-slate-800">N-B 안: 68세 및 100조 선제저축형</p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">수령 시기를 68세로 늦추되 초반 100조 원 선제 저축. 이후 매해 들어갈 보조 국고를 7.5조 원대로 크게 절감.</p>
                  </div>
                  <div className="p-3 bg-blue-50/30 rounded-xl border border-slate-100">
                    <p className="text-xs font-bold text-slate-800">N-C 안: 68세 및 6.0% 적극투자형</p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">수령 나이 68세로 연기 및 연 6% 고수익 적극적 추진. 국비 세금 의존도를 극적으로 줄임 (단, 성적 부진 시 재정 타격)</p>
                  </div>
                </div>
              )}

              {propTab === "basic" && (
                <div className="space-y-3 animate-fade-in">
                  <div className="p-3 bg-blue-50/30 rounded-xl border border-slate-100">
                    <p className="text-xs font-bold text-slate-800">B-A 안: 보편 평등 40만 원</p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">소득과 무관하게 대상자 전원 월 40만 원 지급. 제도가 매우 간명하고 국민 갈등이 적으나 가용 예산이 비효율적으로 낭비.</p>
                  </div>
                  <div className="p-3 bg-blue-50/30 rounded-xl border border-slate-100">
                    <p className="text-xs font-bold text-slate-800">B-B 안: 선별 두터운 차등형 (20~50만)</p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">하위 50만 원, 중위 35만 원, 상위 20만 원 지급. 정말 굶주리는 소외 노인층에 집중 수혈 가능, 일부 어르신의 서운함 존재.</p>
                  </div>
                  <div className="p-3 bg-blue-50/30 rounded-xl border border-slate-100">
                    <p className="text-xs font-bold text-slate-800">B-C 안: 60조 적립 기금 및 세금상한형</p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">차등 지급(B-B와 동일)하되 2026~27년에 60조 기금을 미리 모아 저축. 정부 연간 조세 부담 상한선을 50조로 강력 통제.</p>
                  </div>
                </div>
              )}

              {propTab === "package" && (
                <div className="space-y-3 animate-fade-in">
                  <div className="p-3 bg-blue-50/30 rounded-xl border border-slate-100">
                    <p className="text-xs font-bold text-slate-800">패키지 P1: 단순 유지 및 공평 배분 (N-A + B-A)</p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">나이 65세 그대로 유지하고 모두 공평하게 분배받는 친숙한 모델. 단, 후손들이 평생 내야 할 세금/기금 부담률 폭증.</p>
                  </div>
                  <div className="p-3 bg-blue-50/30 rounded-xl border border-slate-100">
                    <p className="text-xs font-bold text-slate-800">패키지 P2: 세대 연대 및 가난한 분 집중 (N-B + B-B)</p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">68세 수령 연기 고통을 함께 나누고 가난한 어르신께 두터운 복지를 집중 제공하여 불평등 해소.</p>
                  </div>
                  <div className="p-3 bg-blue-50/30 rounded-xl border border-slate-100">
                    <p className="text-xs font-bold text-slate-800">패키지 P3: 스마트 기금 적립 및 조세 상한 (N-C + B-C)</p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">국민연금 적극 투자로 수익을 늘리고 기초연금 기금 저축(60조 원)으로 다가올 국가 부도와 자녀의 세금 폭탄 사전 방지.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 오른쪽 열: 1차 의사결정 투표 Ballot (60% 공간) */}
        <div className="xl:col-span-7 space-y-6">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            {/* 투표 헤더 */}
            <div className="bg-blue-950 text-white p-6 flex justify-between items-center">
              <div className="flex items-center gap-2">
                <Vote className="w-5 h-5 text-blue-400" />
                <h3 className="text-lg font-extrabold text-white tracking-tight">
                  1차 숙의전 의사결정 투표용지
                </h3>
              </div>
              <span className="text-[10px] font-extrabold text-slate-300 bg-blue-900/80 px-2.5 py-1 rounded">
                STEP 02
              </span>
            </div>

            <div className="p-6 md:p-8 space-y-8">
              
              {/* 국민연금 개혁안 선택 */}
              <div className="space-y-4">
                <div className="border-l-4 border-blue-600 pl-3.5 py-0.5">
                  <h4 className="text-xs font-extrabold text-slate-500 tracking-wider uppercase">QUESTION 01</h4>
                  <p className="text-sm font-bold text-slate-800 mt-1">내가 가장 지지하는 국민연금 계획을 골라주세요.</p>
                </div>

                <div className="space-y-2.5">
                  {nationalOptions.map((opt) => (
                    <button
                      key={opt.value}
                      id={`opt-nat-${opt.value}`}
                      type="button"
                      onClick={() => changeVote("nationalPension", opt.value)}
                      className={`w-full text-left p-3.5 rounded-xl border transition-all flex justify-between items-start cursor-pointer ${
                        voteData.nationalPension === opt.value
                          ? "border-blue-600 bg-blue-50/30 shadow-sm"
                          : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <div className="space-y-1 pr-4">
                        <p className={`text-xs md:text-sm font-bold ${voteData.nationalPension === opt.value ? "text-blue-900" : "text-slate-800"}`}>
                          {opt.label}
                        </p>
                        <p className="text-[11px] text-slate-500 leading-relaxed">{opt.desc}</p>
                      </div>
                      <div className={`w-4 h-4 rounded-full border flex items-center justify-center mt-1 flex-shrink-0 ${
                        voteData.nationalPension === opt.value ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white"
                      }`}>
                        {voteData.nationalPension === opt.value && <Check className="w-2.5 h-2.5 stroke-[3]" />}
                      </div>
                    </button>
                  ))}
                </div>

                {/* 국민연금 추가 문항: 고려기준 및 척도 */}
                {voteData.nationalPension !== "" && voteData.nationalPension !== "NONE" && (
                  <div className="p-4 bg-slate-50 rounded-xl border border-slate-200 space-y-4 animate-fade-in" id="nat-sub-questions">
                    <div className="space-y-2">
                      <label className="text-[11px] font-extrabold text-slate-600 block">Q1-A. 이 계획을 고르실 때 가장 눈여겨본 최고 중요 핵심 가치는? <span className="text-rose-500">*</span></label>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                        {reasons.map((r) => (
                          <button
                            key={r.value}
                            id={`reason-nat-${r.value}`}
                            type="button"
                            onClick={() => changeVote("nationalReason", r.value)}
                            className={`py-2 text-center text-[10px] rounded-lg border font-bold transition-all cursor-pointer ${
                              voteData.nationalReason === r.value
                                ? "bg-blue-600 border-blue-600 text-white"
                                : "bg-white border-slate-200 text-slate-600 hover:bg-slate-100"
                            }`}
                          >
                            {r.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* 확신도 */}
                      <div className="space-y-1.5">
                        <div className="flex justify-between items-center text-[10px] font-bold text-slate-600">
                          <span>선택에 대한 안심/확신 점수</span>
                          <span className="text-blue-600 font-extrabold">{voteData.nationalConfidence}%</span>
                        </div>
                        <input
                          id="national-confidence-slider"
                          type="range"
                          min={0}
                          max={100}
                          step={10}
                          value={voteData.nationalConfidence}
                          onChange={(e) => changeVote("nationalConfidence", parseInt(e.target.value))}
                          className="w-full accent-blue-600 cursor-pointer h-1.5 bg-slate-200 rounded-lg"
                        />
                      </div>

                      {/* 세대 형평성 */}
                      <div className="space-y-1.5">
                        <label className="text-[10px] font-bold text-slate-600 block">미래 세대(자녀들)에 공정한가? (1~7점)</label>
                        <div className="flex justify-between gap-1">
                          {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                            <button
                              key={score}
                              id={`nat-fair-${score}`}
                              type="button"
                              onClick={() => changeVote("nationalFairness", score)}
                              className={`flex-1 py-1 text-[10px] font-extrabold border rounded transition-all cursor-pointer ${
                                voteData.nationalFairness === score ? "bg-blue-600 text-white border-blue-600" : "bg-white text-slate-600 hover:bg-slate-100"
                              }`}
                            >
                              {score}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* 기초연금 개혁안 선택 */}
              <div className="space-y-4">
                <div className="border-l-4 border-blue-600 pl-3.5 py-0.5">
                  <h4 className="text-xs font-extrabold text-slate-500 tracking-wider uppercase">QUESTION 02</h4>
                  <p className="text-sm font-bold text-slate-800 mt-1">내가 가장 지지하는 기초연금 계획을 골라주세요.</p>
                </div>

                <div className="space-y-2.5">
                  {basicOptions.map((opt) => (
                    <button
                      key={opt.value}
                      id={`opt-bas-${opt.value}`}
                      type="button"
                      onClick={() => changeVote("basicPension", opt.value)}
                      className={`w-full text-left p-3.5 rounded-xl border transition-all flex justify-between items-start cursor-pointer ${
                        voteData.basicPension === opt.value
                          ? "border-blue-600 bg-blue-50/30 shadow-sm"
                          : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <div className="space-y-1 pr-4">
                        <p className={`text-xs md:text-sm font-bold ${voteData.basicPension === opt.value ? "text-blue-900" : "text-slate-800"}`}>
                          {opt.label}
                        </p>
                        <p className="text-[11px] text-slate-500 leading-relaxed">{opt.desc}</p>
                      </div>
                      <div className={`w-4 h-4 rounded-full border flex items-center justify-center mt-1 flex-shrink-0 ${
                        voteData.basicPension === opt.value ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white"
                      }`}>
                        {voteData.basicPension === opt.value && <Check className="w-2.5 h-2.5 stroke-[3]" />}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* 통합 패키지 선택 */}
              <div className="space-y-4">
                <div className="border-l-4 border-blue-600 pl-3.5 py-0.5">
                  <h4 className="text-xs font-extrabold text-slate-500 tracking-wider uppercase">QUESTION 03</h4>
                  <p className="text-sm font-bold text-slate-800 mt-1">두 연금을 균형 있게 묶어서 제시된 최종 패키지 계획 선택</p>
                </div>

                <div className="space-y-2.5">
                  {integratedPackages.map((opt) => (
                    <button
                      key={opt.value}
                      id={`opt-pkg-${opt.value}`}
                      type="button"
                      onClick={() => changeVote("integratedPackage", opt.value)}
                      className={`w-full text-left p-3.5 rounded-xl border transition-all flex justify-between items-start cursor-pointer ${
                        voteData.integratedPackage === opt.value
                          ? "border-blue-600 bg-blue-50/30 shadow-sm"
                          : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <div className="space-y-1 pr-4">
                        <p className={`text-xs md:text-sm font-bold ${voteData.integratedPackage === opt.value ? "text-blue-900" : "text-slate-800"}`}>
                          {opt.label}
                        </p>
                        <p className="text-[11px] text-slate-500 leading-relaxed">{opt.desc}</p>
                      </div>
                      <div className={`w-4 h-4 rounded-full border flex items-center justify-center mt-1 flex-shrink-0 ${
                        voteData.integratedPackage === opt.value ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white"
                      }`}>
                        {voteData.integratedPackage === opt.value && <Check className="w-2.5 h-2.5 stroke-[3]" />}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* ⚠️ 재정 충돌 완화 의사결정 (N-B + B-C 동시 선택 시 확장) */}
              {isConflict && (
                <div className="p-5 bg-rose-50 border border-rose-200 rounded-2xl space-y-4 animate-fade-in" id="conflict-resolution-wrapper">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="w-6 h-6 text-rose-600 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-extrabold text-rose-900 leading-tight">⚠️ 재정 일시 과부하 비상: 초반에 총 160조 원을 한꺼번에 저축할 수 있을까요?</p>
                      <p className="text-[11px] text-rose-700 mt-1 leading-relaxed">
                        개별 선택하신 <strong>국민연금안 (N-B: 초반 100조 원 저축)</strong>과 <strong>기초연금안 (B-C: 초반 60조 원 저축)</strong>을 동시에 추진할 경우, 우리나라는 2026~2027년 단 2년 동안 무려 <strong>160조 원</strong>의 막대한 세수 준비금을 마련해야 합니다. 나랏빚이나 세금 폭탄 없이 이 재정적 충돌을 어떻게 조절하고 완화하시겠습니까? <span className="text-rose-600">*</span>
                      </p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    {[
                      { value: "opt1", label: "1. 그래도 160조 원의 초반 저축을 온전히 추진합니다.", desc: "나랏빚을 지더라도 장래 세대의 완전한 복지 안정망을 기어코 구축합니다." },
                      { value: "opt2", label: "2. 국민연금에 처음 모으려던 100조 원의 규모를 절반 이하로 줄입니다.", desc: "국민연금 선제 저축을 낮춰 당장의 국고 부담을 줄이고 나중에 땜빵합니다." },
                      { value: "opt3", label: "3. 기초연금 기금으로 모으려던 60조 원을 크게 축소합니다.", desc: "기초기금 형성을 포기하고 필요한 금액을 해마다 국비 세금으로 꼬박꼬박 조달합니다." },
                      { value: "opt4", label: "4. 초반 준비금을 내는 기간을 2년에서 4~5년으로 더 늘려 쪼개어 냅니다.", desc: "연간 80조 원 부담을 매년 30조 원대로 연장 조절하여 부드럽게 분산 수용합니다." },
                    ].map((cOpt) => (
                      <button
                        key={cOpt.value}
                        id={`conflict-res-${cOpt.value}`}
                        type="button"
                        onClick={() => changeVote("conflictResolution", cOpt.value)}
                        className={`w-full text-left p-3 rounded-xl border text-xs transition-all flex justify-between items-start cursor-pointer ${
                          voteData.conflictResolution === cOpt.value
                            ? "border-rose-600 bg-rose-50 font-bold"
                            : "border-slate-200 hover:bg-slate-50/50"
                        }`}
                      >
                        <div className="space-y-0.5">
                          <p className={voteData.conflictResolution === cOpt.value ? "text-rose-950 font-extrabold" : "text-slate-800 font-bold"}>{cOpt.label}</p>
                          <p className="text-[10px] text-slate-500 leading-normal">{cOpt.desc}</p>
                        </div>
                        <div className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center mt-0.5 shrink-0 ${
                          voteData.conflictResolution === cOpt.value ? "border-rose-600 bg-rose-600 text-white" : "border-slate-300 bg-white"
                        }`}>
                          {voteData.conflictResolution === cOpt.value && <Check className="w-2 h-2 stroke-[3]" />}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 투표 완료 가이드 및 전송 */}
              <div className="pt-6 border-t border-slate-100 flex flex-col md:flex-row justify-between items-center gap-4">
                <p className="text-[11px] text-slate-400 font-semibold leading-relaxed max-w-md">
                  💡 1, 2, 3 질문에 대한 답안을 모두 가볍게 제출하셔야 하며, N-B + B-C 충돌 시에는 조율 안까지 응답 완료해야 합니다.
                </p>
                <button
                  id="btn-submit-vote1"
                  onClick={handleNext}
                  disabled={!checkValidation()}
                  className={`w-full md:w-auto py-3 px-8 rounded-xl text-xs md:text-sm font-extrabold transition-all shadow-sm flex items-center justify-center gap-2 ${
                    checkValidation()
                      ? "bg-blue-600 text-white hover:bg-blue-700 hover:shadow cursor-pointer"
                      : "bg-slate-100 text-slate-400 cursor-not-allowed border border-slate-200"
                  }`}
                >
                  투표 내용 임시저장 및 3단계로 이동
                  <ArrowRight className="w-4 h-4 stroke-[2.5]" />
                </button>
              </div>

            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
