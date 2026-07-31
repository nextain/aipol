import React, { useState } from "react";
import { Landmark, Shield, Wallet, ArrowRight, Table, HelpCircle, Check } from "lucide-react";

interface ExpertProposalsProps {
  onNext: () => void;
}

export default function ExpertProposals({ onNext }: ExpertProposalsProps) {
  const [activeTab, setActiveTab] = useState<"national" | "basic" | "package">("national");

  // 기초연금 연도별 총재정소요 데이터 (B-A 정액형 vs B-B/B-C 차등형)
  const basicBudgetTable = [
    { year: 2026, ba: "36.39조 원", bbc: "40.63조 원", diff: "+4.24조 원" },
    { year: 2030, ba: "41.99조 원", bbc: "46.56조 원", diff: "+4.57조 원" },
    { year: 2035, ba: "46.59조 원", bbc: "51.15조 원", diff: "+4.56조 원" },
    { year: 2040, ba: "51.70조 원", bbc: "56.19조 원", diff: "+4.49조 원" },
    { year: 2045, ba: "52.89조 원", bbc: "57.00조 원", diff: "+4.11조 원" },
    { year: 2050, ba: "54.10조 원", bbc: "57.82조 원", diff: "+3.72조 원" },
    { year: 2060, ba: "51.65조 원", bbc: "54.61조 원", diff: "+2.96조 원" },
    { year: 2070, ba: "47.96조 원", bbc: "50.52조 원", diff: "+2.56조 원" },
  ];

  return (
    <div className="bg-white rounded-xl shadow-md border border-slate-200 overflow-hidden" id="expert-proposals-container">
      {/* 탭 구조 */}
      <div className="flex border-b border-slate-200 bg-slate-50/50">
        <button
          id="btn-prop-tab-national"
          onClick={() => setActiveTab("national")}
          className={`flex-1 py-4 text-center font-bold transition-all border-b-2 text-xs md:text-sm flex items-center justify-center gap-1.5 ${
            activeTab === "national"
              ? "border-indigo-600 text-indigo-700 bg-white font-extrabold"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Shield className="w-4 h-4 text-indigo-600" />
          국민연금 개혁안 (N-A/B/C)
        </button>
        <button
          id="btn-prop-tab-basic"
          onClick={() => setActiveTab("basic")}
          className={`flex-1 py-4 text-center font-bold transition-all border-b-2 text-xs md:text-sm flex items-center justify-center gap-1.5 ${
            activeTab === "basic"
              ? "border-indigo-600 text-indigo-700 bg-white font-extrabold"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Wallet className="w-4 h-4 text-indigo-600" />
          기초연금 개혁안 (B-A/B/C)
        </button>
        <button
          id="btn-prop-tab-package"
          onClick={() => setActiveTab("package")}
          className={`flex-1 py-4 text-center font-bold transition-all border-b-2 text-xs md:text-sm flex items-center justify-center gap-1.5 ${
            activeTab === "package"
              ? "border-indigo-600 text-indigo-700 bg-white font-extrabold"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Landmark className="w-4 h-4 text-indigo-600" />
          실험용 통합 패키지 (P1/2/3)
        </button>
      </div>

      <div className="p-6 md:p-8">
        {/* 국민연금 개혁안 */}
        {activeTab === "national" && (
          <div className="space-y-6" id="national-proposals-panel">
            <div className="border-l-4 border-indigo-500 pl-4 py-1">
              <h2 className="text-base md:text-lg font-bold text-slate-850">국민연금 개혁 대안 상세 비교 (공통: 보험료율 13% / 소득대체율 43%)</h2>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                보험료와 받는 금액의 대체 비율은 13%와 43%로 고정하고, **수급 연령, 자금 수급 방식, 그리고 목표 투자수익률**에 따라 3개 안으로 구분됩니다.
              </p>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
              {/* N-A */}
              <div className="border border-slate-200 rounded-xl p-5 hover:shadow-md transition-all flex flex-col justify-between bg-slate-50/20">
                <div>
                  <div className="flex justify-between items-center border-b border-slate-100 pb-3 mb-4">
                    <span className="bg-indigo-100 text-indigo-800 text-xs font-bold px-2.5 py-1 rounded-full">N-A 안</span>
                    <h3 className="font-bold text-slate-800 text-base">현행 나이 유지형</h3>
                  </div>
                  <ul className="space-y-3.5 text-xs md:text-sm text-slate-600">
                    <li>⏱️ <strong>연금 받는 나이:</strong> <span className="font-bold text-indigo-650">만 65세 그대로 유지</span></li>
                    <li>📈 <strong>목표 투자수익률:</strong> 매년 연 5.5% 굴리기 가정</li>
                    <li>💰 <strong>나라 지원 방식:</strong> 처음에 따로 저축해 두는 돈 없이, <span className="font-semibold text-rose-600">매년 우리나라 총 소득(GDP)의 0.6%</span>를 국가 세금으로 꼬박꼬박 지원합니다.</li>
                    <li>📉 <strong>매년 들어가는 세금:</strong> 연간 약 <strong>18조 원</strong> 이상 (나라 경제가 커질수록 이 세금 부담도 비례해서 늘어납니다)</li>
                    <li>📊 <strong>안정성 점수:</strong> 보통</li>
                  </ul>
                </div>
                <div className="mt-6 pt-4 border-t border-slate-150 bg-indigo-50/20 p-3.5 rounded-xl">
                  <p className="text-xs text-slate-700"><strong>👍 좋은 점:</strong> 연금 받는 나이를 늦추지 않아, 은퇴 후 연금 받을 때까지 돈이 없는 공백기가 없습니다.</p>
                  <p className="text-xs text-rose-700 mt-1.5"><strong>👎 아쉬운 점:</strong> 매년 어마어마한 나랏돈(세금)이 계속 들어가기 때문에 미래 자녀들의 세금 부담이 늘어납니다.</p>
                </div>
              </div>

              {/* N-B */}
              <div className="border border-slate-200 rounded-xl p-5 hover:shadow-md transition-all flex flex-col justify-between bg-slate-50/20">
                <div>
                  <div className="flex justify-between items-center border-b border-slate-100 pb-3 mb-4">
                    <span className="bg-indigo-100 text-indigo-800 text-xs font-bold px-2.5 py-1 rounded-full">N-B 안</span>
                    <h3 className="font-bold text-slate-800 text-base">나이 연기 및 세금 아끼기형</h3>
                  </div>
                  <ul className="space-y-3.5 text-xs md:text-sm text-slate-600">
                    <li>⏱️ <strong>연금 받는 나이:</strong> <span className="font-bold text-amber-650">만 68세로 점차 늦춤 (2046년까지)</span></li>
                    <li>📈 <strong>목표 투자수익률:</strong> 매년 연 5.5% 굴리기 가정</li>
                    <li>💰 <strong>나라 지원 방식:</strong> <span className="font-bold text-indigo-600">초반 2년 동안 총 100조 원을 먼저 연금 통장에 저축</span>해 두고, 이후에는 매년 GDP의 0.25%만 조금씩 보탭니다.</li>
                    <li>📉 <strong>매년 들어가는 세금:</strong> 선제 저축 덕분에 매년 보탤 세금이 연간 약 <strong>7.5조 원</strong> 수준으로 대폭 줄어듭니다.</li>
                    <li>📊 <strong>안정성 점수:</strong> 든든함</li>
                  </ul>
                </div>
                <div className="mt-6 pt-4 border-t border-slate-150 bg-amber-50/30 p-3.5 rounded-xl">
                  <p className="text-xs text-slate-700"><strong>👍 좋은 점:</strong> 처음에 든든하게 저축을 해두기 때문에, 나중에 정기적으로 들어갈 세금 부담을 가장 크게 줄여줍니다.</p>
                  <p className="text-xs text-rose-700 mt-1.5"><strong>👎 아쉬운 점:</strong> 연금을 68세부터 늦게 받으므로 소득 공백기가 생길 수 있고, 당장 초반에 100조 원을 마련해야 합니다.</p>
                </div>
              </div>

              {/* N-C */}
              <div className="border border-slate-200 rounded-xl p-5 hover:shadow-md transition-all flex flex-col justify-between bg-slate-50/20">
                <div>
                  <div className="flex justify-between items-center border-b border-slate-100 pb-3 mb-4">
                    <span className="bg-indigo-100 text-indigo-800 text-xs font-bold px-2.5 py-1 rounded-full">N-C 안</span>
                    <h3 className="font-bold text-slate-800 text-base">나이 연기 및 고수익 투자형</h3>
                  </div>
                  <ul className="space-y-3.5 text-xs md:text-sm text-slate-600">
                    <li>⏱️ <strong>연금 받는 나이:</strong> <span className="font-bold text-amber-650">만 68세로 점차 늦춤 (2046년까지)</span></li>
                    <li>📈 <strong>목표 투자수익률:</strong> <span className="font-bold text-indigo-650">연 6.0%로 더 공격적인 고수익 도전</span></li>
                    <li>💰 <strong>나라 지원 방식:</strong> 평상시에는 매년 정해놓고 주는 국가 세금은 전혀 없습니다. 그러다 기금이 부족해질 비상 상황이 생길 때만 필요분을 지원합니다.</li>
                    <li>📉 <strong>매년 들어가는 세금:</strong> 평소 나랏돈 의존도가 가장 낮아 국가 재정에 큰 무리를 주지 않습니다.</li>
                    <li>📊 <strong>안정성 점수:</strong> 매우 탄탄함 (단, 수익률 달성 시)</li>
                  </ul>
                </div>
                <div className="mt-6 pt-4 border-t border-slate-150 bg-indigo-50/30 p-3.5 rounded-xl">
                  <p className="text-xs text-slate-700"><strong>👍 좋은 점:</strong> 세금을 거의 쓰지 않고도 기금을 불려 연금 통장을 가장 오랫동안 든든하게 유지할 수 있습니다.</p>
                  <p className="text-xs text-rose-700 mt-1.5"><strong>👎 아쉬운 점:</strong> 전 세계 자산 시장이 얼어붙어 목표 수익률(6.0%)을 달성하지 못하면 재정이 흔들릴 위험이 큽니다.</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 기초연금 개혁안 */}
        {activeTab === "basic" && (
          <div className="space-y-6" id="basic-proposals-panel">
            <div className="border-l-4 border-indigo-500 pl-4 py-1">
              <h2 className="text-base md:text-lg font-bold text-slate-850">기초연금 개혁 대안 상세 비교 (공통 수급연령: 65세 / 대상: 중위소득 100% 이하)</h2>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                기초연금액을 모두에게 똑같이 줄 것인가(B-A), 소득수준에 따라 다르게 차등 지급할 것인가(B-B), 아니면 차등 지급과 동시에 미래 세대 폭탄 방지용 기금을 만들 것인가(B-C)의 대립입니다.
              </p>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
              {/* B-A */}
              <div className="border border-slate-200 rounded-xl p-5 hover:shadow-md transition-all flex flex-col justify-between bg-slate-50/20">
                <div>
                  <div className="flex justify-between items-center border-b border-slate-100 pb-3 mb-4">
                    <span className="bg-indigo-100 text-indigo-800 text-xs font-bold px-2.5 py-1 rounded-full">B-A 안</span>
                    <h3 className="font-bold text-slate-800 text-base">모두 똑같이 받기형</h3>
                  </div>
                  <div className="space-y-3 text-xs md:text-sm text-slate-600">
                    <p className="p-2.5 bg-slate-100 rounded text-center text-slate-800 font-bold">
                      소득에 상관없이 대상 전원에게 월 40만 원 똑같이 지급
                    </p>
                    <ul className="space-y-2.5 mt-2">
                      <li>• <strong>비교적 넉넉한 노인층(상위):</strong> 월 40만 원</li>
                      <li>• <strong>평범한 노인층(중위):</strong> 월 40만 원</li>
                      <li>• <strong>형편이 어려운 노인층(하위):</strong> 월 40만 원</li>
                      <li>• <strong>초기 따로 모아둘 기금:</strong> 없음 (매년 세금으로 충당)</li>
                    </ul>
                  </div>
                </div>
                <div className="mt-6 pt-4 border-t border-slate-150 bg-indigo-50/20 p-3.5 rounded-xl">
                  <p className="text-xs text-slate-700"><strong>👍 좋은 점:</strong> 모든 어르신들께 똑같은 금액을 나누어 드리기 때문에 제도가 매우 단순하고 사회적 다툼이 적습니다.</p>
                  <p className="text-xs text-rose-700 mt-1.5"><strong>👎 아쉬운 점:</strong> 형편이 정말 어려운 분들께 더 많이 챙겨드리기 어렵고, 들어갈 세금이 매년 크게 불어납니다.</p>
                </div>
              </div>

              {/* B-B */}
              <div className="border border-slate-200 rounded-xl p-5 hover:shadow-md transition-all flex flex-col justify-between bg-slate-50/20">
                <div>
                  <div className="flex justify-between items-center border-b border-slate-100 pb-3 mb-4">
                    <span className="bg-indigo-100 text-indigo-800 text-xs font-bold px-2.5 py-1 rounded-full">B-B 안</span>
                    <h3 className="font-bold text-slate-800 text-base">어려운 분 더 많이 돕기형</h3>
                  </div>
                  <div className="space-y-3 text-xs md:text-sm text-slate-600">
                    <p className="p-2.5 bg-slate-100 rounded text-center text-rose-800 font-bold">
                      형편이 어려울수록 더 많이 받게 설계
                    </p>
                    <ul className="space-y-2.5 mt-2">
                      <li>• <strong>비교적 넉넉한 노인층:</strong> <span className="font-bold text-slate-700">월 20만 원</span> (감액)</li>
                      <li>• <strong>평범한 노인층:</strong> 월 35만 원</li>
                      <li>• <strong>형편이 어려운 노인층:</strong> <span className="font-bold text-indigo-650">월 50만 원</span> (증액 지원)</li>
                      <li>• <strong>초기 따로 모아둘 기금:</strong> 없음 (전액 매년 세금으로 꼬박꼬박 지출)</li>
                    </ul>
                  </div>
                </div>
                <div className="mt-6 pt-4 border-t border-slate-150 bg-amber-50/30 p-3.5 rounded-xl">
                  <p className="text-xs text-slate-700"><strong>👍 좋은 점:</strong> 같은 나랏돈으로도 당장 굶주리거나 아픈, 진짜 어려운 어르신분들께 월 50만 원씩 더 두텁게 집중적으로 도와드릴 수 있습니다.</p>
                  <p className="text-xs text-rose-700 mt-1.5"><strong>👎 아쉬운 점:</strong> 넉넉했던 구간의 분들은 월 20만 원으로 깎이게 되므로, 일부 어르신들의 섭섭함이나 반발이 생길 수 있습니다.</p>
                </div>
              </div>

              {/* B-C */}
              <div className="border border-slate-200 rounded-xl p-5 hover:shadow-md transition-all flex flex-col justify-between bg-slate-50/20">
                <div>
                  <div className="flex justify-between items-center border-b border-slate-100 pb-3 mb-4">
                    <span className="bg-indigo-100 text-indigo-800 text-xs font-bold px-2.5 py-1 rounded-full">B-C 안</span>
                    <h3 className="font-bold text-slate-800 text-base">어려운 분 돕기 및 미래대비형</h3>
                  </div>
                  <div className="space-y-3 text-xs md:text-sm text-slate-600">
                    <p className="p-2.5 bg-slate-100 rounded text-center text-indigo-800 font-bold">
                      어려운 분 지원 차등 적용 + 미래 대비 60조 원 저축
                    </p>
                    <ul className="space-y-2.5 mt-2">
                      <li>• <strong>받는 연금액 수준:</strong> 형편에 따라 월 20만 / 35만 / 50만 원 (B-B와 동일)</li>
                      <li>• <strong>미래 대비 저축:</strong> <span className="font-bold text-indigo-650">2026~2027년에 나라 세금에서 총 60조 원을 모아</span> 따로 기금 통장으로 굴립니다.</li>
                      <li>• <strong>자녀들 세금 차단제:</strong> 정부 세금은 <span className="font-semibold text-slate-800">연간 최대 50조 원</span>까지만 보태고, 부족한 초과분은 미리 모아둔 60조 기금의 원금과 이자에서 꺼내 씁니다.</li>
                    </ul>
                  </div>
                </div>
                <div className="mt-6 pt-4 border-t border-slate-150 bg-indigo-50/30 p-3.5 rounded-xl">
                  <p className="text-xs text-slate-700"><strong>👍 좋은 점:</strong> 미래에 어르신들이 훨씬 많아질 때도 미리 불려둔 60조 기금 이자로 메울 수 있어서, 미래 세대의 세금 폭탄을 안전하게 예방합니다.</p>
                  <p className="text-xs text-rose-700 mt-1.5"><strong>👎 아쉬운 점:</strong> 당장 초기 2년 동안 기초연금만을 위해 60조 원이라는 엄청난 나랏돈 저축금을 마련해야 합니다.</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 실험용 통합 패키지 3개 */}
        {activeTab === "package" && (
          <div className="space-y-6" id="package-proposals-panel">
            <div className="border-l-4 border-indigo-500 pl-4 py-1">
              <h2 className="text-base md:text-lg font-bold text-slate-850">국민연금 + 기초연금 종합 연계 실험용 패키지 (P1 / P2 / P3)</h2>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                각 연금의 개별 선택이 초래할 수 있는 국고 충돌 문제를 예방하고, 가치관의 일관성을 검증하기 위해 연구진 수치를 기준으로 조합한 세 가지 종합 개혁 패키지입니다.
              </p>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
              {/* P1 */}
              <div className="border-2 border-slate-200 hover:border-indigo-500 rounded-xl p-5 hover:shadow-md transition-all flex flex-col justify-between bg-slate-50/10">
                <div>
                  <div className="flex justify-between items-center border-b border-slate-150 pb-3 mb-4">
                    <span className="bg-slate-700 text-white text-xs font-bold px-3 py-1 rounded-full">패키지 P1</span>
                    <h3 className="font-bold text-slate-800 text-base">나이 유지 및 똑같이 받기</h3>
                  </div>
                  <p className="text-xs text-slate-500 mb-4 font-medium leading-relaxed bg-slate-100 p-2.5 rounded border border-slate-200">
                    "연금 받기 시작하는 나이를 65세로 유지하고 기초연금도 모두 똑같이 받지만, 연금 부족분을 메우기 위해 매년 아주 많은 세금을 국가에서 지원해야 합니다."
                  </p>
                  <ul className="space-y-2.5 text-xs md:text-sm text-slate-600">
                    <li>⚙️ <strong>국민연금:</strong> N-A 안 (65세 유지, 매년 GDP의 0.6% 세금 수혈)</li>
                    <li>💰 <strong>매년 들어갈 세금:</strong> 연간 약 18조 원 이상에서 나라가 커질수록 계속 증가</li>
                    <li>📉 <strong>기초연금:</strong> B-A 안 (소득 100% 이하에게 모두 똑같이 월 40만 원 지급)</li>
                    <li>📊 <strong>기초연금 세금(2050년):</strong> 연간 약 54.10조 원 지출</li>
                    <li>💼 <strong>따로 모아둘 기금:</strong> 없음 (그때그때 세금으로 해결)</li>
                  </ul>
                </div>
                <div className="mt-6 pt-4 border-t border-slate-150">
                  <div className="text-xs font-bold text-indigo-700">🎯 지향하는 가치:</div>
                  <p className="text-xs text-slate-650 mt-1 leading-relaxed">연금을 정해진 나이에 안정적으로 받고 모두 똑같이 나누는 친숙하고 심플한 방식 선호</p>
                  <div className="text-xs font-bold text-rose-800 mt-2">⚠️ 감당해야 할 짐:</div>
                  <p className="text-xs text-rose-700 mt-1 leading-relaxed">우리 후손들과 자녀들이 평생 감당해야 할 세금이 매년 크게 늘어남</p>
                </div>
              </div>

              {/* P2 */}
              <div className="border-2 border-slate-200 hover:border-indigo-500 rounded-xl p-5 hover:shadow-md transition-all flex flex-col justify-between bg-slate-50/10">
                <div>
                  <div className="flex justify-between items-center border-b border-slate-150 pb-3 mb-4">
                    <span className="bg-amber-600 text-white text-xs font-bold px-3 py-1 rounded-full">패키지 P2</span>
                    <h3 className="font-bold text-slate-800 text-base">세대 간 분담 및 어려운 분 돕기</h3>
                  </div>
                  <p className="text-xs text-slate-500 mb-4 font-medium leading-relaxed bg-amber-50/20 p-2.5 rounded border border-amber-100">
                    "연금 받는 나이를 68세로 늦추는 고통을 분담하고, 처음에 100조 원을 저축해 나중 세금을 줄입니다. 대신 기초연금은 형편이 어려운 분께 집중해 드립니다."
                  </p>
                  <ul className="space-y-2.5 text-xs md:text-sm text-slate-600">
                    <li>⚙️ <strong>국민연금:</strong> N-B 안 (68세로 점진 연기, 초기에 100조 원 선제 저축)</li>
                    <li>💰 <strong>매년 들어갈 세금:</strong> 선제 저축 효과로 매년 약 7.5조 원 수준으로 크게 절감</li>
                    <li>📉 <strong>기초연금:</strong> B-B 안 (형편에 따라 월 20만 / 35만 / 50만 원 차등 지원)</li>
                    <li>📊 <strong>기초연금 세금(2050년):</strong> 연간 약 57.82조 원 지출</li>
                    <li>💼 <strong>따로 모아둘 기금:</strong> 국민연금용 100조 원만 선제 저축</li>
                  </ul>
                </div>
                <div className="mt-6 pt-4 border-t border-slate-150">
                  <div className="text-xs font-bold text-amber-800">🎯 지향하는 가치:</div>
                  <p className="text-xs text-slate-650 mt-1 leading-relaxed">진짜 가난한 어르신들께 국가 복지를 더 두텁게 집중하고 미래 청년들과 짐을 나누어 가짐</p>
                  <div className="text-xs font-bold text-rose-800 mt-2">⚠️ 감당해야 할 짐:</div>
                  <p className="text-xs text-rose-700 mt-1 leading-relaxed">연금을 3년 늦게 받게 되므로 공백기가 생길 수 있고, 초기에 100조 원이라는 큰 저축금을 세수에서 조달해야 함</p>
                </div>
              </div>

              {/* P3 */}
              <div className="border-2 border-indigo-200 hover:border-indigo-500 rounded-xl p-5 hover:shadow-md transition-all flex flex-col justify-between bg-indigo-50/5">
                <div>
                  <div className="flex justify-between items-center border-b border-indigo-150 pb-3 mb-4">
                    <span className="bg-indigo-600 text-white text-xs font-bold px-3 py-1 rounded-full">패키지 P3</span>
                    <h3 className="font-bold text-slate-800 text-base">기금운용 및 재정저축 대비</h3>
                  </div>
                  <p className="text-xs text-slate-500 mb-4 font-medium leading-relaxed bg-indigo-50/20 p-2.5 rounded border border-indigo-150">
                    "연금 나이를 68세로 늦추되 고수익 투자를 시도하고, 기초연금도 60조 기금을 미리 저축해 정부가 보탤 세금 총량에 연간 50조 상한 캡을 씌웁니다."
                  </p>
                  <ul className="space-y-2.5 text-xs md:text-sm text-slate-600">
                    <li>⚙️ <strong>국민연금:</strong> N-C 안 (68세로 연기, 연 6.0% 적극 투자수익 추진, 정기 세금 수혈 없음)</li>
                    <li>💰 <strong>매년 들어갈 세금:</strong> 평소에는 국가 재정 세금이 한 푼도 들어가지 않음</li>
                    <li>📉 <strong>기초연금:</strong> B-C 안 (소득 차등 + 초기에 60조 원을 따로 저축 기금화하여 불림)</li>
                    <li>📊 <strong>기초연금 세금(2050년):</strong> 나라 세금은 50조로 통제하고, 나머지 부족액(7.82조)은 모아둔 60조 기금 이자로 지출</li>
                    <li>💼 <strong>따로 모아둘 기금:</strong> 기초연금용 60조 원</li>
                  </ul>
                </div>
                <div className="mt-6 pt-4 border-t border-slate-150">
                  <div className="text-xs font-bold text-indigo-800">🎯 지향하는 가치:</div>
                  <p className="text-xs text-slate-650 mt-1 leading-relaxed">나랏돈을 그냥 쓰기보다는 선제적으로 기금을 모아 금융 시장에 굴려서 벌어들인 돈으로 미래 연금 부담을 스마트하게 해결</p>
                  <div className="text-xs font-bold text-rose-800 mt-2">⚠️ 감당해야 할 짐:</div>
                  <p className="text-xs text-rose-700 mt-1 leading-relaxed">금융 자산 투자가 부진할 때 위험이 따르며, 처음에 기초연금 저축용으로 60조 원의 큰 재원을 내놓아야 함</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 진행 제어 버튼 */}
        <div className="mt-8 flex justify-between items-center border-t border-slate-200 pt-6">
          <p className="text-xs text-slate-450 font-semibold leading-relaxed max-w-xl">
            💡 국민연금과 기초연금의 각 구체적인 수치와 조합 원리를 정확히 파악하신 후 1차 투표로 이동해 주세요.
          </p>

          <button
            id="btn-proposals-complete"
            onClick={onNext}
            className="py-3 px-6 bg-indigo-600 text-white rounded-xl text-xs md:text-sm font-bold hover:bg-indigo-700 hover:shadow shadow-sm transition-all flex items-center gap-1.5 cursor-pointer"
          >
            3단계: 숙의 전 1차 투표 진행하기
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
