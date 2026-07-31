import React from "react";
import { UserProfile, VoteData } from "../types";
import { User, Calendar, Shield, Sparkles, AlertTriangle, TrendingDown, DollarSign, ArrowRight } from "lucide-react";

interface AIScenarioAnalysisProps {
  profile: UserProfile;
  votes: VoteData;
  onNext: () => void;
}

export default function AIScenarioAnalysis({ profile, votes, onNext }: AIScenarioAnalysisProps) {
  // 사용자의 연령대별 해석 텍스트 동적 렌더링
  const getAgeContext = () => {
    switch (profile.ageGroup) {
      case "20-29":
        return {
          title: "청년 세대 (20대)",
          burden: "연금 보험료가 월급의 13%로 오르면, 은퇴할 때까지 약 35년 넘게 꾸준히 많은 보험료를 내야 합니다. 연금 기금이 정말 오랫동안 안전하게 남아있을지 불안해하는 젊은 세대입니다.",
          payoff: "개혁이 성공하면 기금이 바닥나는 시기가 2096년 이후로 대폭 늦춰집니다. 덕분에 내가 은퇴했을 때 연금을 안정적으로 온전히 돌려받을 수 있게 되는 큰 안심을 얻는 세대입니다.",
          suggestion: "만약 초반에 돈을 많이 모아두거나 투자 수익을 세게 내는 계획이 잘 안 풀리면, 먼 미래에 소득의 상당 부분을 세금이나 보험료로 한꺼번에 부담해야 할 수도 있습니다."
        };
      case "30-39":
        return {
          title: "청장년 세대 (30대)",
          burden: "직장에서 열심히 일하는 시기에 보험료가 월급의 9%에서 13%로 오르는 것을 직접 경험하며, 당장 매달 생활비에 대한 고민이 늘어날 수 있습니다.",
          payoff: "기존 기금 고갈 예정 시기였던 2065년 즈음에 내가 딱 은퇴할 나이(만 69~78세)가 되기 때문에, 이번 연금 개혁의 성공 여부에 직접적인 노후 생계가 걸린 가장 직접적인 주인공 세대입니다.",
          suggestion: "초반 저축(N-B)이나 기금 적립(B-C) 등으로 나라 세금 부담을 줄여두지 않으면, 본인이 은퇴해서 연금을 받기 시작할 때 감당하기 힘든 세금 부담을 맞이할 수도 있습니다."
        };
      case "40-49":
        return {
          title: "허리 세대 (40대)",
          burden: "은퇴할 때까지 15~25년 정도 남은 경제의 주축이지만, 자녀 교육비나 내 집 마련 등으로 한창 지출이 가장 많을 시기라 늘어나는 보험료 부담이 한층 더 무겁게 느껴질 수 있습니다.",
          payoff: "내가 나중에 은퇴하고 노후에 연금으로 돌려받는 돈 비율(소득대체율)이 기존 40%에서 43%로 상향 고정되므로, 노후 소득을 한결 더 든든하게 받게 되는 혜택을 누립니다.",
          suggestion: "연금을 받기 시작하는 나이가 만 68세로 늦춰지는 안(N-B, N-C)이 채택되면, 원래 다니던 직장을 그만두는 시점(예: 60세)과 연금을 받기 시작하는 나이 사이에 소득이 끊기는 '공백 기간'이 길게 발생할 수 있어 준비가 필요합니다."
        };
      case "50-59":
        return {
          title: "은퇴 직전 세대 (50대)",
          burden: "국민연금 보험료를 낼 기간이 10년 미만으로 짧기 때문에, 보험료율이 오르더라도 청년층에 비해 매달 누적되는 총부담 타격은 상대적으로 적은 편입니다.",
          payoff: "인상된 소득대체율(43%)의 높은 보장 혜택은 가까운 시일 내에 온전히 누리면서 은퇴 시점에 안전하게 연금 제도로 들어설 수 있는 가장 안정적인 세대입니다.",
          suggestion: "받기 시작하는 나이가 만 68세로 천천히 조정되는 시기이므로 내 출생연도에 따라 개시 시점(65~68세)이 다릅니다. 기초연금을 어려운 사람 위주로 차등 지급하면, 본인이 소득 하위층일 경우 받는 혜택이 대폭 늘어날 수 있습니다."
        };
      case "60-69":
      case "70+":
        return {
          title: "수급 당사자 및 고령 세대",
          burden: "이제 국민연금 보험료를 추가로 내야 하는 납부 의무는 거의 끝났거나 이미 종료되어, 보험료율 인상에 따른 경제적 실소득 감소 타격은 완전히 비껴갑니다.",
          payoff: "이미 정해진 국민연금 수급액은 매달 그대로 보장받습니다. 다만 매달 추가로 수령하는 '기초연금'의 지급 방식에 따라 직접적인 혜택 크기가 변하게 됩니다.",
          suggestion: "기초연금을 모두에게 똑같이 나누어 주지 않고 형편이 더 어려운 어르신 위주로 몰아주는 방식(B-B/B-C 안)이 되면, 소득 수준에 따라 기초연금이 기존보다 줄어들 수 있어 노령층 내에서의 이해관계가 다를 수 있습니다."
        };
      default:
        return {
          title: "가입 세대",
          burden: "국민연금 보험료가 월급의 13%로 오르면 전체적인 실수령액이 조금 줄어들어 매달 생활비에 소폭 부담이 커질 수 있습니다.",
          payoff: "나라 세금을 정교하게 보태거나 투자 수익을 더 내서 기금이 일찍 고갈되는 것을 막으면, 내가 늙어서도 걱정 없이 매달 연금을 받을 수 있게 됩니다.",
          suggestion: "연금을 몇 살부터 타게 되는지의 공백기와 내가 받을 기초연금 액수가 어떻게 달라지는지 나에게 맞춰 꼼꼼히 확인해 두는 것이 좋습니다."
        };
    }
  };

  const ageData = getAgeContext();

  return (
    <div className="bg-white rounded-xl shadow-md border border-slate-200 overflow-hidden animate-fade-in" id="ai-scenario-container">
      {/* 그래픽 장식 헤더 */}
      <div className="bg-gradient-to-br from-indigo-950 via-slate-900 to-indigo-900 text-white p-6 md:p-8">
        <div className="flex items-center gap-2 text-indigo-300 text-xs font-bold uppercase tracking-wider">
          <Sparkles className="w-4 h-4 text-amber-400" />
          <span>Personal AI Analysis</span>
        </div>
        <h2 className="text-xl md:text-2xl font-extrabold tracking-tight mt-2">내 프로필로 확인해보는 연금개혁 AI 맞춤 시나리오 분석</h2>
        <p className="text-xs md:text-sm text-slate-300 mt-2 leading-relaxed">
          내가 입력한 나이, 소득, 은퇴 시기와 1차 투표 내용을 바탕으로 AI가 내게 미치는 실질적인 노후 영향을 아주 쉽게 풀어서 알려드립니다.
        </p>
      </div>

      <div className="p-6 md:p-8 space-y-8">
        {/* 사용자 정보 요약 카드 */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 p-4.5 bg-slate-50/50 rounded-xl border border-slate-200" id="user-profile-summary-card">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shadow-sm">
              <User className="w-5 h-5" />
            </div>
            <div>
              <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wide">내 세대 분류</p>
              <p className="text-sm font-extrabold text-slate-800">{ageData.title}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shadow-sm">
              <DollarSign className="w-5 h-5" />
            </div>
            <div>
              <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wide">내 한달 가구 소득</p>
              <p className="text-sm font-extrabold text-slate-800">
                {profile.incomeLevel === "under_2m" && "200만 원 미만"}
                {profile.incomeLevel === "2m_4m" && "200만 ~ 400만 원"}
                {profile.incomeLevel === "4m_6m" && "400만 ~ 600만 원"}
                {profile.incomeLevel === "6m_8m" && "600만 ~ 800만 원"}
                {profile.incomeLevel === "over_8m" && "800만 원 이상"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shadow-sm">
              <Calendar className="w-5 h-5" />
            </div>
            <div>
              <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wide">희망하는 은퇴 나이</p>
              <p className="text-sm font-extrabold text-slate-800">만 {profile.retireAge}세 은퇴</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shadow-sm">
              <Shield className="w-5 h-5" />
            </div>
            <div>
              <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wide">1차 지지 계획 패키지</p>
              <p className="text-sm font-extrabold text-slate-800">
                {votes.integratedPackage === "P1" && "P1 (나이유지·보편상향)"}
                {votes.integratedPackage === "P2" && "P2 (나이연장·차등상향)"}
                {votes.integratedPackage === "P3" && "P3 (나이연장·저축대비)"}
                {votes.integratedPackage === "NONE" && "적합한 안 없음"}
                {votes.integratedPackage === "UNDECIDED" && "판단 유보"}
                {!votes.integratedPackage && "미지정"}
              </p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* 시나리오 A & B (개인 관점) */}
          <div className="space-y-6">
            <h3 className="text-xs font-extrabold text-slate-500 tracking-wider uppercase border-b pb-2 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-indigo-600"></span>
              내 프로필로 보는 맞춤 노후 가상 분석
            </h3>

            {/* 시나리오 A */}
            <div className="p-5 bg-indigo-50/20 rounded-xl border border-indigo-100/80 space-y-3" id="scenario-a-card">
              <h4 className="text-xs md:text-sm font-bold text-indigo-900 flex items-center gap-1.5">
                <span className="w-1.5 h-3 bg-indigo-600 rounded"></span>
                <span>시나리오 A : 내 평생 세금 납부와 연금 수령액</span>
              </h4>
              <div className="space-y-2.5 text-xs md:text-sm text-slate-700 leading-relaxed">
                <p><strong>내가 일하며 낼 보험료 부담:</strong> {ageData.burden}</p>
                <p className="mt-2 pt-2 border-t border-indigo-100/40"><strong>내가 노후에 돌려받을 연금 혜택:</strong> {ageData.payoff}</p>
              </div>
            </div>

            {/* 시나리오 B */}
            <div className="p-5 bg-amber-50/20 rounded-xl border border-amber-100/80 space-y-3" id="scenario-b-card">
              <h4 className="text-xs md:text-sm font-bold text-amber-900 flex items-center gap-1.5">
                <span className="w-1.5 h-3 bg-amber-500 rounded"></span>
                <span>시나리오 B: 퇴직 나이와 연금 받는 나이 사이 소득 공백기</span>
              </h4>
              <div className="space-y-2 text-xs md:text-sm text-slate-700 leading-relaxed">
                <p>
                  내가 계획한 퇴직 예정 나이는 <strong>만 {profile.retireAge}세</strong>입니다. 
                  만약 <strong>N-B</strong> 또는 <strong>N-C</strong> 안이 가동되어 국민연금을 받기 시작하는 나이가 <strong>만 68세</strong>로 상향 조정된다면, 
                  {profile.retireAge < 68 ? (
                    <span className="text-rose-700 font-extrabold ml-1 underline underline-offset-2 animate-pulse">
                      일을 그만둔 뒤 무려 {68 - profile.retireAge}년 동안 연금을 타지 못해 소득이 완전히 끊기는 공백기(크레바스)가 발생하게 됩니다!
                    </span>
                  ) : (
                    <span className="text-indigo-700 font-extrabold ml-1">
                      내가 은퇴를 계획한 나이가 만 68세보다 늦기 때문에, 일을 그만둔 후 소득이 아예 단절되는 공백기 걱정을 덜 수 있습니다.
                    </span>
                  )}
                </p>
                <p className="mt-2 text-slate-600">
                  {ageData.suggestion}
                </p>
                <div className="p-3 bg-white rounded-xl border border-amber-200/80 mt-3 text-xs text-slate-600 shadow-sm leading-relaxed">
                  💡 <strong>내 노후를 위한 체크포인트:</strong> 연금을 받기 전까지 생기는 빈틈은 기초연금(월 20만~50만) 및 개인퇴직연금(IRP)을 통해 미리 계획적으로 대비해야 생활을 안전하게 이어갈 수 있습니다.
                </div>
              </div>
            </div>
          </div>

          {/* 시나리오 C & D (거시/국가 관점) */}
          <div className="space-y-6">
            <h3 className="text-xs font-extrabold text-slate-500 tracking-wider uppercase border-b pb-2 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-indigo-600"></span>
              국가 전체의 연금 기금과 세금 안전판 테스트
            </h3>

            {/* 시나리오 C */}
            <div className="p-5 bg-slate-50/50 rounded-xl border border-slate-200 space-y-3" id="scenario-c-card">
              <h4 className="text-xs md:text-sm font-bold text-slate-800 flex items-center gap-1.5">
                <span className="w-1.5 h-3 bg-slate-500 rounded"></span>
                <span>시나리오 C: 미래 세대가 감당할 국가 세금 부담의 실제 크기</span>
              </h4>
              <div className="space-y-2 text-xs md:text-sm text-slate-600 leading-relaxed">
                <p>
                  기초연금을 모두에게 골고루 줄지, 어려운 분께 더 몰아줄지에 따라 2050년에 필요한 나라 세금 예산이 다릅니다.
                </p>
                <ul className="space-y-1.5 mt-2 bg-white p-3.5 rounded-xl border border-slate-200 text-slate-700 font-mono text-xs shadow-sm">
                  <li className="flex justify-between border-b border-slate-100 pb-1.5">
                    <span className="text-slate-500">모두 똑같이 받기(B-A) 2050년 세금:</span>
                    <span className="font-extrabold text-slate-800">54.10조 원</span>
                  </li>
                  <li className="flex justify-between border-b border-slate-100 pb-1.5">
                    <span className="text-slate-500">어려운 분 더 돕기(B-B/B-C) 2050년 세금:</span>
                    <span className="font-extrabold text-indigo-600">57.82조 원</span>
                  </li>
                  <li className="flex justify-between pt-0.5">
                    <span className="text-slate-500">노인 양극화 완화를 위한 추가 지출 편차:</span>
                    <span className="font-extrabold text-rose-600">+3.72조 원</span>
                  </li>
                </ul>
                <p className="mt-2 text-slate-600">
                  <strong>저축 기금(B-C 안)의 예산 완충 장치:</strong> B-B 안은 57.82조 원 전체를 그 시기 우리 자녀들이 낼 당해 세금으로만 감당해야 합니다. 반면, 미리 60조 원을 적립해 굴리는 <strong>B-C 안</strong>은 비축된 돈과 수익금에서 <strong>13.5% (약 7.82조 원)</strong>을 직접 조달해 쓰기 때문에, 정부의 일반 세금 투입은 연 50조 원 한도 내로 가뿐하게 묶여 경제 충격을 피할 수 있습니다.
                </p>
              </div>
            </div>

            {/* /시나리오 D */}
            <div className="p-5 bg-rose-50/20 rounded-xl border border-rose-100/80 space-y-3" id="scenario-d-card">
              <h4 className="text-xs md:text-sm font-bold text-rose-950 flex items-center gap-1.5">
                <TrendingDown className="w-4 h-4 text-rose-600" />
                <span>시나리오 D : 투자 성적이 나빠졌을 때 생길 위험 (목표수익률 6%)</span>
              </h4>
              <div className="space-y-2 text-xs md:text-sm text-slate-700 leading-relaxed">
                <p>
                  세금 지원을 최대한 안 받고 자체 투자 수익만으로 연금 고갈을 연장하려는 <strong>P3 패키지 (N-C 국민연금)</strong>는 매년 <strong>연 6.0%</strong>라는 매우 높고 우수한 주식 및 글로벌 대체투자 실적이 꾸준히 달성된다는 긍정적인 가정을 바탕으로 세워졌습니다.
                </p>
                <div className="p-3.5 bg-white rounded-xl border border-rose-200 text-xs shadow-sm leading-relaxed">
                  <p className="font-bold text-rose-800 flex items-center gap-1">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    수익률 미달에 따른 기금 바닥 위험
                  </p>
                  <p className="text-slate-550 mt-1">
                    만약 해외 금융 위기 등으로 기금 투자 성적이 기대치에 못 미치고 <strong>5.5%</strong> 혹은 <strong>5.0%</strong> 수준으로 떨어지거나 연속 마이너스를 기록하게 되면, 기금이 든든히 버틸 것으로 기대했던 미래 타임라인은 물거품이 되고 연금이 빠르게 흔들리게 됩니다.
                  </p>
                </div>
                <p className="text-xs text-slate-500 mt-2">
                  이 기금 의존형 계획은 금융 시장의 부침에 극도로 약하기 때문에, 투자 성적이 나쁜 주기에 이르면 즉시 국민들에게 세금을 엄청나게 거두어 긴급 수혈하거나, 연금액을 덜 주도록 급격한 법 개정을 다시 거쳐야 하는 변동성 위험을 명백하게 안고 가야 합니다.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* 진행 통제 바 */}
        <div className="mt-8 flex justify-between items-center border-t border-slate-200 pt-6">
          <p className="text-xs text-slate-450 font-semibold max-w-md hidden md:block">
            💡 내 프로필과 은퇴 나이, 투자 리스크, 세금 예측을 분석해 주는 AI 맞춤 종합 보고서를 모두 읽어보셨습니다.
          </p>

          <button
            id="btn-scenario-complete"
            onClick={onNext}
            className="w-full md:w-auto py-3 px-6 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs md:text-sm font-bold shadow-sm transition-all flex items-center justify-center gap-1.5 cursor-pointer hover:shadow"
          >
            5단계: 소그룹 AI 실시간 대화 및 의견 교환방으로 이동
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
