import React from "react";
import { UserProfile, PerceptionAnswers } from "../types";
import { Check, ClipboardList, Shield, Landmark, User, DollarSign, Calendar, HeartHandshake } from "lucide-react";

interface PreSurveyProps {
  profile: UserProfile;
  setProfile: (profile: UserProfile) => void;
  perception: PerceptionAnswers;
  setPerception: (perception: PerceptionAnswers) => void;
  // knowledge remains in the prop signature for compatibility, but we automate or pre-fill it for simplicity
  knowledge: any;
  setKnowledge: (knowledge: any) => void;
  onNext: () => void;
}

export default function PreSurvey({
  profile,
  setProfile,
  perception,
  setPerception,
  onNext,
}: PreSurveyProps) {
  const ageGroups = [
    { value: "20-29", label: "20대" },
    { value: "30-39", label: "30대" },
    { value: "40-49", label: "40대" },
    { value: "50-59", label: "50대" },
    { value: "60-69", label: "60대" },
    { value: "70+", label: "70대 이상" },
  ];

  const incomeLevels = [
    { value: "under_2m", label: "200만 원 미만" },
    { value: "2m_4m", label: "200만 ~ 400만 원" },
    { value: "4m_6m", label: "400만 ~ 600만 원" },
    { value: "6m_8m", label: "600만 ~ 800만 원" },
    { value: "over_8m", label: "800만 원 이상" },
  ];

  const valueQuestions = [
    {
      key: "q1",
      title: "연금 지속성 신뢰도",
      desc: "내가 노후에 연금을 타기 시작할 때도 국가 기금이 고갈되지 않고 안전하게 줄 것이라 생각하십니까?",
      leftLabel: "전혀 믿지 않는다",
      rightLabel: "매우 신뢰한다",
    },
    {
      key: "q3", // q3 is used for tax-financed safety net in the radar chart
      title: "재정 안정화 추구 방식",
      desc: "연금 재정이 고갈될 때 국가 세금(재정)을 투입해 지키는 것보다, 기금을 아끼기 위해 본인 보험료를 13% 수준으로 우선 인상하는 것에 동의하십니까?",
      leftLabel: "국고 세금 수혈 우선",
      rightLabel: "본인 보험료 인상 우선",
    },
    {
      key: "q6", // q6 matches poor protection/distribution in result radar
      title: "기초연금 지급 철학",
      desc: "모든 노인에게 공평하게 나누어 주기보다, 형편이 더 어려운 어르신 위주로 두텁고 넉넉하게 몰아주는 것에 찬성하십니까?",
      leftLabel: "똑같이 골고루 지급",
      rightLabel: "어려운 분 집중 지원",
    },
  ];

  const checkValidation = () => {
    return (
      profile.ageGroup !== "" &&
      profile.incomeLevel !== "" &&
      profile.isMember !== "" &&
      profile.retireAge >= 20 &&
      profile.retireAge <= 90 &&
      profile.basicPensionEligible !== "" &&
      perception.q1 > 0 &&
      perception.q3 > 0 &&
      perception.q6 > 0
    );
  };

  const handleNextStep = () => {
    // Fill other perception answers with baseline neutral values (4) for radar chart compatibility
    const completePerception: PerceptionAnswers = {
      q1: perception.q1 || 4,
      q2: 4, // default neutral
      q3: perception.q3 || 4,
      q4: 4, // default neutral
      q5: 4, // default neutral
      q6: perception.q6 || 4,
      q7: 4, // default neutral
      q8: 4, // default neutral
    };
    setPerception(completePerception);
    onNext();
  };

  return (
    <div className="space-y-6 animate-fade-in" id="presurvey-simple-view">
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
        {/* 헤더 */}
        <div className="bg-gradient-to-r from-slate-900 to-blue-950 text-white p-8 md:p-10">
          <div className="flex items-center gap-2.5 text-blue-400 text-xs font-bold uppercase tracking-widest font-mono">
            <ClipboardList className="w-4 h-4 text-blue-400" />
            <span>STEP 01</span>
          </div>
          <h2 className="text-2xl md:text-3xl font-extrabold tracking-tight mt-2 text-white">
            사전조사 및 가치 성향 파악
          </h2>
          <p className="text-xs md:text-sm text-slate-300 mt-2 leading-relaxed">
            내가 입력한 나이, 소득, 은퇴 계획에 비추어 AI가 실시간 노후 영향 분석 보고서를 구성합니다.
            간단히 응답하시고 똑똑하고 정밀한 연금 숙의 실험에 동참해 보세요.
          </p>
        </div>

        <div className="p-8 md:p-10 space-y-10">
          {/* 섹션 1: 프로필 입력 */}
          <div className="space-y-6">
            <div className="border-l-4 border-blue-600 pl-4 py-0.5">
              <h3 className="text-base font-extrabold text-slate-900 flex items-center gap-2">
                <User className="w-5 h-5 text-blue-600" />
                나의 가입 기본 정보 (프로필)
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">시뮬레이션을 구동하기 위한 가치 있는 5가지 기본값입니다.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 bg-slate-50/50 p-6 rounded-2xl border border-slate-200/60">
              {/* 연령대 */}
              <div className="space-y-2">
                <label className="text-xs font-bold text-slate-700 block tracking-wide uppercase">
                  1. 귀하의 연령대 <span className="text-rose-500">*</span>
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {ageGroups.map((group) => (
                    <button
                      key={group.value}
                      id={`age-${group.value}`}
                      type="button"
                      onClick={() => setProfile({ ...profile, ageGroup: group.value as any })}
                      className={`py-2 px-1 text-xs rounded-xl border text-center transition-all font-semibold cursor-pointer ${
                        profile.ageGroup === group.value
                          ? "border-blue-600 bg-blue-50 text-blue-900 shadow-sm font-extrabold"
                          : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {group.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 가구 소득 */}
              <div className="space-y-2">
                <label className="text-xs font-bold text-slate-700 block tracking-wide uppercase">
                  2. 월 평균 가구 총 소득 <span className="text-rose-500">*</span>
                </label>
                <div className="space-y-1.5">
                  {incomeLevels.map((level) => (
                    <button
                      key={level.value}
                      id={`income-${level.value}`}
                      type="button"
                      onClick={() => setProfile({ ...profile, incomeLevel: level.value as any })}
                      className={`w-full py-2 px-4 text-xs rounded-xl border text-left transition-all font-semibold cursor-pointer ${
                        profile.incomeLevel === level.value
                          ? "border-blue-600 bg-blue-50 text-blue-900 shadow-sm font-extrabold"
                          : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {level.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 연금가입 여부 */}
              <div className="space-y-3">
                <label className="text-xs font-bold text-slate-700 block tracking-wide uppercase">
                  3. 현재 국민연금 납부 여부 <span className="text-rose-500">*</span>
                </label>
                <div className="flex gap-3">
                  <button
                    id="member-yes"
                    type="button"
                    onClick={() => setProfile({ ...profile, isMember: "yes" })}
                    className={`flex-1 py-3 rounded-xl border text-xs font-semibold transition-all cursor-pointer ${
                      profile.isMember === "yes"
                        ? "border-blue-600 bg-blue-50 text-blue-900 shadow-sm font-extrabold"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    가입 중 (보험료 납부)
                  </button>
                  <button
                    id="member-no"
                    type="button"
                    onClick={() => setProfile({ ...profile, isMember: "no" })}
                    className={`flex-1 py-3 rounded-xl border text-xs font-semibold transition-all cursor-pointer ${
                      profile.isMember === "no"
                        ? "border-blue-600 bg-blue-50 text-blue-900 shadow-sm font-extrabold"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    미가입 (수급자·피부양자)
                  </button>
                </div>
              </div>

              {/* 은퇴희망 연령 */}
              <div className="space-y-3">
                <label className="text-xs font-bold text-slate-700 block tracking-wide uppercase">
                  4. 내가 계획 중인 실제 은퇴 연령 <span className="text-rose-500">*</span>
                </label>
                <div className="flex items-center gap-3">
                  <input
                    id="retire-age-input"
                    type="number"
                    min={20}
                    max={90}
                    value={profile.retireAge}
                    onChange={(e) => setProfile({ ...profile, retireAge: parseInt(e.target.value) || 60 })}
                    className="w-24 px-4 py-2 border border-slate-250 rounded-xl text-slate-800 text-sm font-extrabold focus:border-blue-600 focus:ring-1 focus:ring-blue-600 focus:outline-none transition-all bg-white"
                  />
                  <span className="text-xs text-slate-500 font-semibold">세 은퇴 예정 (20~90세 입력 가능)</span>
                </div>
              </div>

              {/* 기초연금 가상 적합도 */}
              <div className="space-y-3 md:col-span-2 border-t border-slate-200/60 pt-4 mt-2">
                <label className="text-xs font-bold text-slate-700 block tracking-wide uppercase">
                  5. 내가 만 65세 이상 도달 시 '기초연금'(소득하위 70%)을 수급할 가능성 <span className="text-rose-500">*</span>
                </label>
                <div className="flex gap-2.5">
                  {["yes", "maybe", "no"].map((val) => (
                    <button
                      key={val}
                      id={`basic-eligible-${val}`}
                      type="button"
                      onClick={() => setProfile({ ...profile, basicPensionEligible: val as any })}
                      className={`flex-1 py-2.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer ${
                        profile.basicPensionEligible === val
                          ? "border-blue-600 bg-blue-50 text-blue-900 shadow-sm font-extrabold"
                          : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {val === "yes" ? "수급 가능성 높음" : val === "maybe" ? "유동적 / 모름" : "수급 불가(고자산/고소득)"}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* 섹션 2: 가치 인식 검사 */}
          <div className="space-y-6">
            <div className="border-l-4 border-blue-600 pl-4 py-0.5">
              <h3 className="text-base font-extrabold text-slate-900 flex items-center gap-2">
                <HeartHandshake className="w-5 h-5 text-blue-600" />
                나의 사회 연금 철학과 평소 신념 (가치관)
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">내가 생각하는 이상적인 연금 제도의 분배 철학과 재정 조율 수준을 선택해 주세요.</p>
            </div>

            <div className="space-y-5">
              {valueQuestions.map((q) => {
                const currentVal = (perception as any)[q.key] || 0;
                return (
                  <div key={q.key} className="p-6 bg-slate-50/50 rounded-2xl border border-slate-200/60 space-y-4" id={`q-container-${q.key}`}>
                    <div>
                      <span className="text-[11px] font-extrabold text-blue-600 uppercase tracking-widest bg-blue-100/50 px-2 py-0.5 rounded">
                        {q.title}
                      </span>
                      <p className="text-xs md:text-sm font-bold text-slate-800 mt-2 leading-relaxed">
                        {q.desc}
                      </p>
                    </div>

                    <div className="flex items-center justify-between gap-3 max-w-xl">
                      <span className="text-[10px] text-slate-400 font-extrabold w-24 text-left leading-tight shrink-0">
                        {q.leftLabel}
                      </span>
                      <div className="flex gap-2 justify-center flex-1">
                        {[1, 2, 3, 4, 5, 6, 7].map((score) => (
                          <button
                            key={score}
                            id={`percept-${q.key}-${score}`}
                            type="button"
                            onClick={() => setPerception({ ...perception, [q.key]: score })}
                            className={`w-9 h-9 md:w-10 md:h-10 rounded-xl border text-xs font-extrabold transition-all flex items-center justify-center cursor-pointer ${
                              currentVal === score
                                ? "bg-blue-600 border-blue-600 text-white shadow-sm"
                                : "bg-white border-slate-200 text-slate-600 hover:border-blue-300 hover:text-blue-700"
                            }`}
                          >
                            {score}
                          </button>
                        ))}
                      </div>
                      <span className="text-[10px] text-blue-600 font-extrabold w-24 text-right leading-tight shrink-0">
                        {q.rightLabel}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 진행 전송 바 */}
          <div className="pt-6 border-t border-slate-200 flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-xs text-slate-400 font-medium leading-relaxed">
              💡 별표(*)와 3개의 연금 분배 가치 질문에 모두 가볍게 답변하시면 2단계 실시간 시뮬레이션 보드로 넘어갑니다.
            </p>
            <button
              id="btn-next-step"
              onClick={handleNextStep}
              disabled={!checkValidation()}
              className={`w-full md:w-auto py-3.5 px-8 rounded-xl text-xs md:text-sm font-extrabold tracking-wide transition-all shadow-sm flex items-center justify-center gap-2 ${
                checkValidation()
                  ? "bg-blue-600 hover:bg-blue-700 text-white cursor-pointer hover:shadow"
                  : "bg-slate-100 text-slate-400 cursor-not-allowed border border-slate-200"
              }`}
            >
              입력 완료 및 2단계 시뮬레이션 보드로 이동
              <Check className="w-4 h-4 stroke-[2.5]" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
