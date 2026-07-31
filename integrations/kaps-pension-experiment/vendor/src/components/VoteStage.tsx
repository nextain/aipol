import React, { useState } from "react";
import { VoteData, NationalOption, BasicOption, IntegratedOption } from "../types";
import { ArrowRight, ArrowLeft, Check, Shield, Wallet, Landmark, AlertTriangle, Info } from "lucide-react";

interface VoteStageProps {
  stageTitle: string; // "1차 투표 (숙의 전)" or "2차 투표 (숙의 후)"
  isSecondVote?: boolean;
  voteData: VoteData;
  setVoteData: (data: VoteData) => void;
  onComplete: (data: VoteData) => void;
}

export default function VoteStage({
  stageTitle,
  isSecondVote = false,
  voteData,
  setVoteData,
  onComplete,
}: VoteStageProps) {
  const [step, setStep] = useState<"national" | "basic" | "package" | "conflict">("national");

  const nationalOptions = [
    { value: "N-A", label: "N-A 안: 65세부터 받기 (나이 유지형)", desc: "정해진 나이(만 65세)에 바로 연금을 받되, 매년 약 18조 원 수준의 많은 국가 세금이 들어갑니다." },
    { value: "N-B", label: "N-B 안: 68세부터 받기 + 초반 저축 (세금 아끼기형)", desc: "받는 나이를 만 68세로 천천히 늦추고, 초반에 100조 원을 먼저 저축해 나중 세금을 아낍니다." },
    { value: "N-C", label: "N-C 안: 68세부터 받기 + 고수익 투자 (고수익 도전형)", desc: "받는 나이를 만 68세로 천천히 늦추고, 목표 투자 수익률을 연 6%로 높여 세금 지원 없이 기금을 굴립니다." },
    { value: "NONE", label: "마음에 드는 안이 없습니다", desc: "제시된 세 가지 안 모두 동의하기 어렵습니다." },
    { value: "UNDECIDED", label: "아직 잘 모르겠습니다", desc: "조금 더 고민이나 설명이 필요하여 판단을 미룹니다." },
  ];

  const basicOptions = [
    { value: "B-A", label: "B-A 안: 모두 똑같이 받기 (월 40만 원)", desc: "소득과 상관없이 대상 전원에게 월 40만 원을 똑같이 나누어 드립니다." },
    { value: "B-B", label: "B-B 안: 어려운 분 더 많이 받기 (월 20만~50만 원)", desc: "형편이 어려운 어르신은 월 50만 원으로 늘리고, 비교적 넉넉한 분은 월 20만 원으로 줄여서 차등 지급합니다." },
    { value: "B-C", label: "B-C 안: 어려운 분 돕기 + 미래대비 60조 저축", desc: "소득에 따라 다르게 지급(월 20만~50만)하되, 초반에 60조 원을 모아 저축하고 나라 세금 부담을 연 50조로 통제합니다." },
    { value: "NONE", label: "마음에 드는 안이 없습니다", desc: "제시된 세 가지 기초연금안 모두 지지하지 않습니다." },
    { value: "UNDECIDED", label: "아직 잘 모르겠습니다", desc: "조금 더 고민이나 설명이 필요하여 판단을 미룹니다." },
  ];

  const integratedPackages = [
    { value: "P1", label: "패키지 P1: 나이 유지 및 똑같이 받기 (N-A + B-A)", desc: "국민연금 받는 나이를 65세로 유지하고 기초연금도 모두 똑같이 월 40만 원씩 나눕니다." },
    { value: "P2", label: "패키지 P2: 세대 간 고통 분담 및 어려운 분 집중 돕기 (N-B + B-B)", desc: "국민연금 나이를 68세로 늦추고 초반 100조를 저축하며, 기초연금은 형편이 더 어려운 분께 집중해 드립니다." },
    { value: "P3", label: "패키지 P3: 고수익 투자 및 재정저축 대비 (N-C + B-C)", desc: "국민연금은 연 6% 고수익 투자를 시도하고, 기초연금도 60조 저축 기금을 만들어 세금 폭탄을 차단합니다." },
    { value: "NONE", label: "마음에 드는 패키지가 없습니다", desc: "세 가지 패키지 중 지향하는 가치나 위험 부담이 제 생각과 맞지 않습니다." },
    { value: "UNDECIDED", label: "아직 잘 모르겠습니다", desc: "종합적인 효과나 영향력을 좀 더 알아보고 싶습니다." },
  ];

  const reasons = [
    { value: "age", label: "연금 받는 나이" },
    { value: "tax", label: "세금(나랏돈) 부담 수준" },
    { value: "risk", label: "돈을 굴릴 때의 위험성" },
    { value: "sustainability", label: "연금 제도가 오랫동안 유지되는 것" },
    { value: "future_generation", label: "우리 자녀들(청년층)의 세금 부담" },
    { value: "stability", label: "어르신들이 노후에 안정적으로 받는 것" },
  ];

  // 검증 로직
  const checkValidation = () => {
    if (step === "national") {
      const { nationalPension, nationalReason } = voteData;
      if (!nationalPension) return false;
      if (nationalPension !== "NONE" && nationalPension !== "UNDECIDED") {
        return nationalReason !== "";
      }
      return true;
    } else if (step === "basic") {
      return !!voteData.basicPension;
    } else if (step === "package") {
      return !!voteData.integratedPackage;
    } else if (step === "conflict") {
      return !!voteData.conflictResolution;
    }
    return false;
  };

  // 국민연금과 기초연금을 개별적으로 N-B, B-C 동시에 선택했는지 여부
  const hasConflict = voteData.nationalPension === "N-B" && voteData.basicPension === "B-C";

  const handleNext = () => {
    if (step === "national") {
      setStep("basic");
    } else if (step === "basic") {
      setStep("package");
    } else if (step === "package") {
      // 투표가 끝나고, N-B + B-C 조합 충돌이 감지되면 conflict 화면으로 유도, 아니면 종료
      if (hasConflict) {
        setStep("conflict");
      } else {
        onComplete(voteData);
      }
    } else if (step === "conflict") {
      onComplete(voteData);
    }
  };

  const handlePrev = () => {
    if (step === "basic") {
      setStep("national");
    } else if (step === "package") {
      setStep("basic");
    } else if (step === "conflict") {
      setStep("package");
    }
  };

  const changeVote = (field: keyof VoteData, value: any) => {
    setVoteData({ ...voteData, [field]: value });
  };

  return (
    <div className="bg-white rounded-xl shadow-md border border-slate-200 overflow-hidden" id="vote-stage-wrapper">
      {/* 투표 현황 인디케이터 */}
      <div className="bg-slate-900 text-white px-6 py-4.5 flex justify-between items-center shadow-sm">
        <div className="flex items-center gap-2">
          <span className="bg-indigo-600 text-white text-[10px] tracking-wider font-extrabold px-2.5 py-1 rounded-full">VOTE</span>
          <h2 className="text-base md:text-lg font-extrabold tracking-tight">{stageTitle} - 의사결정 시뮬레이션</h2>
        </div>
        <div className="text-xs text-slate-400 font-semibold bg-slate-800/60 px-3 py-1 rounded-lg">
          {step === "national" && "1 / 3 단계: 국민연금"}
          {step === "basic" && "2 / 3 단계: 기초연금"}
          {step === "package" && "3 / 3 단계: 통합 패키지"}
          {step === "conflict" && "⚠️ 재정 조정 단계"}
        </div>
      </div>

      <div className="p-6 md:p-8">
        {/* 단계 1. 국민연금 선택 */}
        {step === "national" && (
          <div className="space-y-6" id="national-vote-panel">
            <div className="border-l-4 border-indigo-500 pl-4 py-1">
              <h3 className="text-base md:text-lg font-bold text-slate-850 flex items-center gap-1.5 leading-snug">
                <Shield className="w-5 h-5 text-indigo-600" />
                Q1. 내가 가장 마음에 드는 국민연금 계획을 골라주세요.
              </h3>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">연금을 언제부터 받을지, 나중에 세금이 얼마나 들어갈지 등을 생각하며 어울리는 계획을 선택해 보세요.</p>
            </div>

            {/* 라디오 리스트 */}
            <div className="space-y-3">
              {nationalOptions.map((opt) => (
                <button
                  key={opt.value}
                  id={`vote-national-${opt.value}`}
                  type="button"
                  onClick={() => changeVote("nationalPension", opt.value)}
                  className={`w-full text-left p-4 rounded-xl border transition-all flex justify-between items-start cursor-pointer ${
                    voteData.nationalPension === opt.value
                      ? "border-indigo-600 bg-indigo-50/20 shadow-sm"
                      : "border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <div className="space-y-1">
                    <p className={`text-xs md:text-sm font-bold ${voteData.nationalPension === opt.value ? "text-indigo-800" : "text-slate-800"}`}>
                      {opt.label}
                    </p>
                    <p className="text-xs text-slate-500 leading-relaxed">{opt.desc}</p>
                  </div>
                  <div className={`w-5 h-5 rounded-full border flex items-center justify-center mt-0.5 flex-shrink-0 ${
                    voteData.nationalPension === opt.value ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 bg-white"
                  }`}>
                    {voteData.nationalPension === opt.value && <Check className="w-3 h-3 stroke-[3]" />}
                  </div>
                </button>
              ))}
            </div>

            {/* 추가 측정 항목들 (의견 표출 및 확신 수준) */}
            {voteData.nationalPension !== "" && voteData.nationalPension !== "NONE" && voteData.nationalPension !== "UNDECIDED" && (
              <div className="bg-slate-50/60 p-5 rounded-xl border border-slate-200 space-y-6 mt-6 transition-all" id="national-extra-questions">
                <h4 className="text-xs font-extrabold text-slate-500 tracking-wider uppercase border-b pb-2">🔍 내 선택의 이유와 생각 더해보기</h4>
                
                {/* 1. 중요 고려 가치 */}
                <div className="space-y-3">
                  <label className="text-xs md:text-sm font-bold text-slate-700 leading-relaxed block">Q1-A. 이 계획을 고르실 때 가장 중요하게 생각하신 핵심 기준은 무엇인가요? <span className="text-red-500">*</span></label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    {reasons.map((r) => (
                      <button
                        key={r.value}
                        id={`reason-national-${r.value}`}
                        type="button"
                        onClick={() => changeVote("nationalReason", r.value)}
                        className={`py-2.5 px-3 text-xs rounded-xl border text-center transition-all cursor-pointer font-semibold ${
                          voteData.nationalReason === r.value
                            ? "border-indigo-600 bg-indigo-50 text-indigo-800 font-extrabold shadow-sm"
                            : "border-slate-200 text-slate-600 bg-white hover:bg-slate-50"
                        }`}
                      >
                        {r.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* 다중 수치 평가 1~7점 */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
                  {/* 확신도 */}
                  <div className="space-y-2">
                    <div className="flex justify-between items-center">
                      <label className="text-xs font-bold text-slate-700">Q1-B. 이 계획을 선택하신 것에 대해 얼마나 안심되거나 확신하시나요? ({voteData.nationalConfidence}점)</label>
                      <span className="text-xs font-extrabold text-indigo-600">{voteData.nationalConfidence}%</span>
                    </div>
                    <input
                      id="national-confidence-slider"
                      type="range"
                      min={0}
                      max={100}
                      step={10}
                      value={voteData.nationalConfidence}
                      onChange={(e) => changeVote("nationalConfidence", parseInt(e.target.value))}
                      className="w-full accent-indigo-600 cursor-pointer h-2 bg-slate-200 rounded-lg"
                    />
                    <div className="flex justify-between text-[10px] text-slate-400 font-medium">
                      <span>0점 (잘 모르겠고 불안함)</span>
                      <span>50점 (반반임)</span>
                      <span>100점 (매우 안심되고 확신함)</span>
                    </div>
                  </div>

                  {/* 세대공정성 */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-700 block leading-tight">Q1-C. 이 계획이 미래 세대(청년과 자녀들)에게 공정하다고 생각하시나요? ({voteData.nationalFairness}점)</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`national-fairness-${score}`}
                          type="button"
                          onClick={() => changeVote("nationalFairness", score)}
                          className={`flex-1 py-1.5 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.nationalFairness === score
                              ? "bg-indigo-600 border-indigo-600 text-white"
                              : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                    <div className="flex justify-between text-[9px] text-slate-400 font-medium">
                      <span>1 (전혀 공정치 않음)</span>
                      <span>7 (매우 공정함)</span>
                    </div>
                  </div>

                  {/* 이익적합도 */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-700 block leading-tight">Q1-D. 이 계획이 나 자신이나 내 가족의 삶에 유리하고 이익이 되나요? ({voteData.nationalBenefit}점)</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`national-benefit-${score}`}
                          type="button"
                          onClick={() => changeVote("nationalBenefit", score)}
                          className={`flex-1 py-1.5 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.nationalBenefit === score
                              ? "bg-indigo-600 border-indigo-600 text-white"
                              : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                    <div className="flex justify-between text-[9px] text-slate-400 font-medium">
                      <span>1 (전혀 유리치 않음)</span>
                      <span>7 (매우 유리함)</span>
                    </div>
                  </div>

                  {/* 실현가능성 */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-700 block leading-tight">Q1-E. 이 계획이 국회에서 실제로 법으로 만들어져 실행될 가능성이 높다고 보시나요? ({voteData.nationalFeasibility}점)</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`national-feasibility-${score}`}
                          type="button"
                          onClick={() => changeVote("nationalFeasibility", score)}
                          className={`flex-1 py-1.5 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.nationalFeasibility === score
                              ? "bg-indigo-600 border-indigo-600 text-white"
                              : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                    <div className="flex justify-between text-[9px] text-slate-400 font-medium">
                      <span>1 (매우 낮음)</span>
                      <span>7 (매우 높음)</span>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 단계 2. 기초연금 선택 */}
        {step === "basic" && (
          <div className="space-y-6" id="basic-vote-panel">
            <div className="border-l-4 border-indigo-500 pl-4 py-1">
              <h3 className="text-base md:text-lg font-bold text-slate-850 flex items-center gap-1.5 leading-snug">
                <Wallet className="w-5 h-5 text-indigo-600" />
                Q2. 내가 가장 마음에 드는 기초연금 계획을 골라주세요.
              </h3>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">모든 어르신께 똑같이 드릴지, 어려운 분께 더 많이 집중해서 드릴지, 미래를 위한 별도의 저축을 해둘지 고민해 보세요.</p>
            </div>

            {/* 라디오 리스트 */}
            <div className="space-y-3">
              {basicOptions.map((opt) => (
                <button
                  key={opt.value}
                  id={`vote-basic-${opt.value}`}
                  type="button"
                  onClick={() => changeVote("basicPension", opt.value)}
                  className={`w-full text-left p-4 rounded-xl border transition-all flex justify-between items-start cursor-pointer ${
                    voteData.basicPension === opt.value
                      ? "border-indigo-600 bg-indigo-50/20 shadow-sm"
                      : "border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <div className="space-y-1">
                    <p className={`text-xs md:text-sm font-bold ${voteData.basicPension === opt.value ? "text-indigo-800" : "text-slate-800"}`}>
                      {opt.label}
                    </p>
                    <p className="text-xs text-slate-500 leading-relaxed">{opt.desc}</p>
                  </div>
                  <div className={`w-5 h-5 rounded-full border flex items-center justify-center mt-0.5 flex-shrink-0 ${
                    voteData.basicPension === opt.value ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 bg-white"
                  }`}>
                    {voteData.basicPension === opt.value && <Check className="w-3 h-3 stroke-[3]" />}
                  </div>
                </button>
              ))}
            </div>

            {/* 추가 측정 항목들 */}
            {voteData.basicPension !== "" && voteData.basicPension !== "NONE" && voteData.basicPension !== "UNDECIDED" && (
              <div className="bg-slate-50/60 p-5 rounded-xl border border-slate-200 space-y-6 mt-6 transition-all" id="basic-extra-questions">
                <h4 className="text-xs font-extrabold text-slate-500 tracking-wider uppercase border-b pb-2">🔍 기초연금에 대한 내 생각 평가하기</h4>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* 저소득 빈곤보호 효과 */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-700 block leading-tight">Q2-A. 이 계획이 형편이 어려운 어르신분들을 실질적으로 잘 도와준다고 생각하시나요? (1~7점)</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`basic-poor-${score}`}
                          type="button"
                          onClick={() => changeVote("basicFairness", score)}
                          className={`flex-1 py-1.5 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.basicFairness === score
                              ? "bg-indigo-600 border-indigo-600 text-white"
                              : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 세대간 공정성 */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-700 block leading-tight">Q2-B. 세금으로 돈을 주는 방식인데, 미래 청년과 우리 자녀들의 부담 크기가 적절하다고 보시나요? (1~7점)</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`basic-gen-${score}`}
                          type="button"
                          onClick={() => changeVote("basicBenefit", score)}
                          className={`flex-1 py-1.5 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.basicBenefit === score
                              ? "bg-indigo-600 border-indigo-600 text-white"
                              : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 조세부담 수용도 */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-700 block leading-tight">Q2-C. 이 계획을 실행하기 위해 내 세금을 더 내거나 세금을 더 늘리는 것을 받아들이실 수 있나요? (1~7점)</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`basic-tax-${score}`}
                          type="button"
                          onClick={() => changeVote("basicFeasibility", score)}
                          className={`flex-1 py-1.5 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.basicFeasibility === score
                              ? "bg-indigo-600 border-indigo-600 text-white"
                              : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 확신수준 */}
                  <div className="space-y-2">
                    <div className="flex justify-between items-center">
                      <label className="text-xs font-bold text-slate-700">Q2-D. 내 기초연금 계획 선택에 대한 스스로의 안심/확신 점수</label>
                      <span className="text-xs font-extrabold text-indigo-600">{voteData.basicConfidence}%</span>
                    </div>
                    <input
                      id="basic-confidence-slider"
                      type="range"
                      min={0}
                      max={100}
                      step={10}
                      value={voteData.basicConfidence}
                      onChange={(e) => changeVote("basicConfidence", parseInt(e.target.value))}
                      className="w-full accent-indigo-600 cursor-pointer h-2 bg-slate-200 rounded-lg"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 단계 3. 통합 패키지 선택 */}
        {step === "package" && (
          <div className="space-y-6" id="package-vote-panel">
            <div className="border-l-4 border-indigo-500 pl-4 py-1">
              <h3 className="text-base md:text-lg font-bold text-slate-850 flex items-center gap-1.5 leading-snug">
                <Landmark className="w-5 h-5 text-indigo-600" />
                Q3. 두 연금을 묶어서 동시에 해결하는 세 가지 패키지 중, 가장 좋은 조합은 무엇이라고 생각하시나요?
              </h3>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">두 연금은 국가 재정과 긴밀하게 얽혀 있으므로, 따로따로가 아닌 하나의 완성된 세트(패키지)로 골라보세요.</p>
            </div>

            {/* 라디오 리스트 */}
            <div className="space-y-3">
              {integratedPackages.map((opt) => (
                <button
                  key={opt.value}
                  id={`vote-package-${opt.value}`}
                  type="button"
                  onClick={() => changeVote("integratedPackage", opt.value)}
                  className={`w-full text-left p-4 rounded-xl border transition-all flex justify-between items-start cursor-pointer ${
                    voteData.integratedPackage === opt.value
                      ? "border-indigo-600 bg-indigo-50/20 shadow-sm"
                      : "border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <div className="space-y-1">
                    <p className={`text-xs md:text-sm font-bold ${voteData.integratedPackage === opt.value ? "text-indigo-800" : "text-slate-800"}`}>
                      {opt.label}
                    </p>
                    <p className="text-xs text-slate-500 leading-relaxed">{opt.desc}</p>
                  </div>
                  <div className={`w-5 h-5 rounded-full border flex items-center justify-center mt-0.5 flex-shrink-0 ${
                    voteData.integratedPackage === opt.value ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 bg-white"
                  }`}>
                    {voteData.integratedPackage === opt.value && <Check className="w-3 h-3 stroke-[3]" />}
                  </div>
                </button>
              ))}
            </div>

            {/* 패키지 심층 다차원 평가 */}
            {voteData.integratedPackage !== "" && voteData.integratedPackage !== "NONE" && voteData.integratedPackage !== "UNDECIDED" && (
              <div className="bg-slate-50/60 p-5 rounded-xl border border-slate-200 space-y-5 mt-6 transition-all" id="package-extra-questions">
                <h4 className="text-xs font-extrabold text-slate-500 tracking-wider uppercase border-b pb-2">🔍 선택한 종합 패키지에 대한 다각도 의견 적기</h4>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* 1. 정부안 수용성 */}
                  <div className="p-4 bg-white rounded-xl border border-slate-200 space-y-2 shadow-sm">
                    <label className="text-xs font-bold text-slate-700 block leading-relaxed">이 패키지가 실제 우리나라의 공식 연금 계획으로 결정된다면 받아들이실 수 있나요?</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`accept-gov-${score}`}
                          type="button"
                          onClick={() => changeVote("acceptAsGovernment", score)}
                          className={`flex-1 py-2 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.acceptAsGovernment === score ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 2. 사회 수용성 */}
                  <div className="p-4 bg-white rounded-xl border border-slate-200 space-y-2 shadow-sm">
                    <label className="text-xs font-bold text-slate-700 block leading-relaxed">나 자신에게 조금 보탬이 덜 되더라도, 사회와 이웃을 위해 응원하고 받아들이실 수 있나요?</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`accept-soc-${score}`}
                          type="button"
                          onClick={() => changeVote("acceptForSociety", score)}
                          className={`flex-1 py-2 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.acceptForSociety === score ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 3. 세대간 형평성 */}
                  <div className="p-4 bg-white rounded-xl border border-slate-200 space-y-2 shadow-sm">
                    <label className="text-xs font-bold text-slate-700 block leading-relaxed">이 패키지는 지금 연금을 받는 분들과 미래에 받을 청년들 사이에 짐 나누기가 공평한가요?</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`gen-fair-${score}`}
                          type="button"
                          onClick={() => changeVote("generationalFairness", score)}
                          className={`flex-1 py-2 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.generationalFairness === score ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 4. 빈곤층 보호 */}
                  <div className="p-4 bg-white rounded-xl border border-slate-200 space-y-2 shadow-sm">
                    <label className="text-xs font-bold text-slate-700 block leading-relaxed">이 패키지가 어렵고 보호가 필요한 어르신분들을 든든하게 잘 보살펴준다고 보시나요?</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`poor-prot-${score}`}
                          type="button"
                          onClick={() => changeVote("poorProtection", score)}
                          className={`flex-1 py-2 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.poorProtection === score ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 5. 지속 가능성 */}
                  <div className="p-4 bg-white rounded-xl border border-slate-200 space-y-2 shadow-sm">
                    <label className="text-xs font-bold text-slate-700 block leading-relaxed">이 패키지는 먼 미래 후손들까지 연금 기금 고갈 없이 오랫동안 잘 지속될까요?</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`sustain-${score}`}
                          type="button"
                          onClick={() => changeVote("sustainability", score)}
                          className={`flex-1 py-2 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.sustainability === score ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          {score}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 6. 리스크 관리 */}
                  <div className="p-4 bg-white rounded-xl border border-slate-200 space-y-2 shadow-sm">
                    <label className="text-xs font-bold text-slate-700 block leading-relaxed">혹시 생길지 모르는 불안 요소(투자 성적 부진, 갑작스러운 세금 상승 등)를 우리 사회가 잘 헤쳐갈 수 있을까요?</label>
                    <div className="flex justify-between gap-1">
                      {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                        <button
                          key={score}
                          id={`risk-manage-${score}`}
                          type="button"
                          onClick={() => changeVote("riskManageable", score)}
                          className={`flex-1 py-2 text-xs font-extrabold border rounded-lg transition-all cursor-pointer ${
                            voteData.riskManageable === score ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-slate-600 hover:bg-slate-50"
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
        )}

        {/* 단계 4. 재정 충돌 완화 의사결정 (N-B + B-C 조합 충돌 발생 시) */}
        {step === "conflict" && (
          <div className="space-y-6" id="conflict-handling-panel">
            <div className="bg-rose-50 border border-rose-200 rounded-xl p-5 flex items-start gap-4">
              <AlertTriangle className="w-8 h-8 text-rose-600 flex-shrink-0 mt-1" />
              <div>
                <h3 className="text-base md:text-lg font-bold text-rose-900 leading-tight">⚠️ 국가 재정 빨간불: 초반에 160조 원을 한꺼번에 저축할 수 있을까요?</h3>
                <p className="text-xs md:text-sm text-rose-800 mt-2 leading-relaxed">
                  내가 개별 선택한 <strong>국민연금안 (N-B: 초반 100조 원 저축)</strong>과 <strong>기초연금안 (B-C: 초반 60조 원 저축)</strong>을 동시에 가동하면, 우리나라는 
                  <span className="font-bold underline ml-1 text-rose-950">2026~2027년 단 2년 동안 무려 160조 원</span>의 엄청난 나랏돈을 모아서 투자 시장에 넣어두어야 합니다.
                </p>
                <p className="text-xs text-rose-700 mt-2 leading-relaxed">
                  당장 나라의 한 해 세금 규모에 비해 너무나도 큰 금액이기 때문에, 심한 세금 인상이나 국채 증가 등으로 나라 경제가 힘들어질 수 있습니다. <strong>이 충격을 어떻게 줄여 연금안을 조율하면 좋을까요?</strong>
                </p>
              </div>
            </div>

            <div className="space-y-3">
              {[
                { value: "opt1", label: "1. 그래도 160조 원의 초반 저축을 온전히 추진합니다.", desc: "어려운 길이지만 미래 세대의 든든함을 위해서라면, 나랏빚을 내서라도 감당해야 합니다." },
                { value: "opt2", label: "2. 국민연금에 처음 모으려던 100조 원의 규모를 절반 이하로 줄입니다.", desc: "국민연금 초반 저축액을 줄여서 지금 세금 부담을 낮추고, 나중에 모자랄 때 조금씩 지원합니다." },
                { value: "opt3", label: "3. 기초연금 기금으로 모으려던 60조 원을 크게 축소합니다.", desc: "기초연금용 대비기금 마련을 최소화하고, 해마다 필요한 예산을 매해 세금으로 메워 나갑니다." },
                { value: "opt4", label: "4. 초반 준비금을 내는 기간을 2년에서 4~5년으로 더 길게 쪼개어 냅니다.", desc: "매년 80조 원씩 내야 하는 막대한 부담을 매년 30조 원대로 나누어 부드럽게 완화합니다." },
                { value: "opt5", label: "5. 다른 통합 패키지(P1~P3)를 다시 골라 재정 충돌을 원천 차단합니다.", desc: "따로따로 고르다 생긴 불일치를 조정하기 위해, 전문가가 균형 있게 짜둔 종합 패키지를 선호합니다." },
              ].map((opt) => (
                <button
                  key={opt.value}
                  id={`conflict-res-${opt.value}`}
                  type="button"
                  onClick={() => changeVote("conflictResolution", opt.value)}
                  className={`w-full text-left p-4 rounded-xl border transition-all flex justify-between items-start cursor-pointer ${
                    voteData.conflictResolution === opt.value
                      ? "border-rose-600 bg-rose-50/50 shadow-sm"
                      : "border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <div className="space-y-1">
                    <p className={`text-xs md:text-sm font-bold ${voteData.conflictResolution === opt.value ? "text-rose-900" : "text-slate-800"}`}>
                      {opt.label}
                    </p>
                    <p className="text-xs text-slate-500 leading-relaxed">{opt.desc}</p>
                  </div>
                  <div className={`w-5 h-5 rounded-full border flex items-center justify-center mt-0.5 flex-shrink-0 ${
                    voteData.conflictResolution === opt.value ? "border-rose-600 bg-rose-600 text-white" : "border-slate-300 bg-white"
                  }`}>
                    {voteData.conflictResolution === opt.value && <Check className="w-3 h-3 stroke-[3]" />}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 제어 바 */}
        <div className="mt-8 flex justify-between items-center border-t border-slate-200 pt-6">
          <button
            id="btn-vote-prev"
            disabled={step === "national"}
            onClick={handlePrev}
            className={`py-2.5 px-4 rounded-xl text-xs md:text-sm font-bold border flex items-center gap-1 transition-all ${
              step === "national"
                ? "border-slate-150 text-slate-300 cursor-not-allowed bg-slate-50"
                : "border-slate-250 text-slate-700 hover:bg-slate-100 cursor-pointer shadow-sm animate-fade-in"
            }`}
          >
            <ArrowLeft className="w-4 h-4" />
            이전 단계로
          </button>

          <p className="text-xs text-slate-450 font-semibold hidden md:block">
            {step === "conflict" ? "⚠️ 개별 선택 불일치 조정 중" : "정교한 연금 수치 기반의 의사결정 수집"}
          </p>

          <button
            id="btn-vote-next"
            disabled={!checkValidation()}
            onClick={handleNext}
            className={`py-2.5 px-6 rounded-xl text-xs md:text-sm font-bold shadow-sm transition-all flex items-center gap-1.5 ${
              checkValidation()
                ? "bg-indigo-600 text-white hover:bg-indigo-700 hover:shadow cursor-pointer"
                : "bg-slate-100 text-slate-400 cursor-not-allowed"
            }`}
          >
            {step === "package" && !hasConflict ? "투표 완료 및 다음 단계로" : step === "conflict" ? "최종 확인 및 단계 저장" : "다음 세부 단계"}
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
