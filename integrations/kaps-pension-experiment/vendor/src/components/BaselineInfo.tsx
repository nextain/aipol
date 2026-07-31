import React, { useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar, AreaChart, Area } from "recharts";
import { Users, AlertTriangle, Landmark, ArrowRight, TrendingUp } from "lucide-react";

interface BaselineInfoProps {
  onNext: () => void;
}

export default function BaselineInfo({ onNext }: BaselineInfoProps) {
  const [subStep, setSubStep] = useState<number>(1);

  // 차트 1: 인구 구조 고령화 전망 (65세 이상 인구 비중)
  const populationData = [
    { year: 2020, ratio: 15.7, support: 21.8, label: "2020년" },
    { year: 2030, ratio: 25.5, support: 38.6, label: "2030년" },
    { year: 2040, ratio: 34.4, support: 60.5, label: "2040년" },
    { year: 2050, ratio: 40.1, support: 78.9, label: "2050년" },
    { year: 2060, ratio: 43.8, support: 92.4, label: "2060년" },
    { year: 2070, ratio: 46.4, support: 104.2, label: "2070년" },
  ];

  // 차트 2: 현행 제도 유지 시 기금 추이 (단위: 백조 원, 2025~2070)
  const fundTrendData = [
    { year: 2025, fund: 1100, income: 60, expense: 45, label: "2025년" },
    { year: 2030, fund: 1450, income: 80, expense: 70, label: "2030년" },
    { year: 2040, fund: 1750, income: 95, expense: 120, label: "2040년" },
    { year: 2048, fund: 1500, income: 105, expense: 160, label: "2048년(정점후하락)" },
    { year: 2055, fund: 950, income: 110, expense: 210, label: "2055년" },
    { year: 2065, fund: 0, income: 120, expense: 280, label: "2065년(완기고갈)" },
    { year: 2070, fund: -600, income: 125, expense: 330, label: "2070년" },
  ];

  return (
    <div className="bg-white rounded-xl shadow-md border border-slate-200 overflow-hidden" id="baseline-info-container">
      {/* 서브 진행 단계 바 */}
      <div className="flex bg-slate-50 border-b border-slate-200">
        {[
          { step: 1, label: "1. 초고령 사회와 인구구조", icon: <Users className="w-4 h-4" /> },
          { step: 2, label: "2. 현행 국민연금의 장기재정 위험", icon: <AlertTriangle className="w-4 h-4" /> },
          { step: 3, label: "3. 노인 빈곤과 기초연금의 딜레마", icon: <Landmark className="w-4 h-4" /> },
        ].map((item) => (
          <button
            key={item.step}
            id={`baseline-tab-${item.step}`}
            onClick={() => setSubStep(item.step)}
            className={`flex-1 py-4 px-4 text-xs md:text-sm font-semibold transition-all border-b-2 flex items-center justify-center gap-2 ${
              subStep === item.step
                ? "border-indigo-600 text-indigo-700 bg-white font-extrabold"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {item.icon}
            <span className="hidden sm:inline">{item.label}</span>
            <span className="sm:hidden">{item.step}단계</span>
          </button>
        ))}
      </div>

      <div className="p-6 md:p-8">
        {/* 화면 1. 인구 구조 */}
        {subStep === 1 && (
          <div className="space-y-6" id="population-screen">
            <div className="bg-indigo-50/50 rounded-xl p-5 border border-indigo-100">
              <h3 className="text-base md:text-lg font-bold text-indigo-900 flex items-center gap-2">
                <Users className="w-5 h-5 text-indigo-600" />
                1. 청년은 줄고 어르신은 빠르게 늘어납니다 (저출생과 고령화)
              </h3>
              <p className="text-xs md:text-sm text-slate-600 mt-1 leading-relaxed">
                대한민국은 전 세계에서 가장 빠른 속도로 나이가 들어가고 있습니다. 연금을 채워줄 청년 세대는 점점 줄어드는 반면, 연금을 수령할 어르신 인구는 엄청나게 많아져 지금의 구조로는 연금을 주기가 점점 어려워집니다.
              </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              {/* 통계 지표 표 */}
              <div className="space-y-4">
                <h4 className="text-sm font-bold text-slate-850 flex items-center gap-1.5 border-b pb-2">
                  <span>📊 한눈에 보는 우리나라 인구 변화 전망</span>
                </h4>
                <div className="overflow-x-auto rounded-xl border border-slate-200 shadow-sm">
                  <table className="w-full text-left border-collapse text-xs md:text-sm">
                    <thead>
                      <tr className="bg-slate-50 text-slate-700 font-bold border-b border-slate-200">
                        <th className="p-3">중요한 통계 지표</th>
                        <th className="p-3 text-right">현재 수준</th>
                        <th className="p-3 text-right text-rose-600 font-extrabold">미래 전망 (2070년 이후)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200/60 text-slate-600">
                      <tr>
                        <td className="p-3 font-semibold text-slate-800">전체 인구 중 어르신(65세 이상) 비중</td>
                        <td className="p-3 text-right">15.7% (2020년)</td>
                        <td className="p-3 text-right font-bold text-rose-600 bg-rose-50/40">46.4% (2070년, 인구 절반)</td>
                      </tr>
                      <tr>
                        <td className="p-3 font-semibold text-slate-800">청년 100명이 책임져야 하는 어르신 수</td>
                        <td className="p-3 text-right">24.4명 (2022년)</td>
                        <td className="p-3 text-right font-bold text-rose-600 bg-rose-50/40">104.2명 (2072년)</td>
                      </tr>
                      <tr>
                        <td className="p-3 font-semibold text-slate-800">청년 대비 어르신 비율</td>
                        <td className="p-3 text-right">청년 4명이 어르신 1명 부양</td>
                        <td className="p-3 text-right font-bold text-rose-600 bg-rose-50/40">일하는 청년보다 어르신이 더 많아짐</td>
                      </tr>
                      <tr>
                        <td className="p-3 font-semibold text-slate-800">연금 받는 분 1명당 보험료 내는 가입자 수</td>
                        <td className="p-3 text-right">3.57명 (2025년)</td>
                        <td className="p-3 text-right font-bold text-rose-600 bg-rose-50/40">0.74명 (2085년, 1명도 안 됨)</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="p-4 bg-rose-50 border border-rose-100 rounded-xl text-rose-900 text-xs md:text-sm leading-relaxed font-medium">
                  <strong>⚠️ 청년들의 감당하기 힘든 짐:</strong> 연금 받는 어르신 1명당 돈을 내는 가입자가 1명 미만으로 떨어지면, 미래에는 일하는 청년 한 명이 은퇴하신 어르신 한두 명을 혼자 온전히 먹여 살려야 한다는 뜻이 됩니다.
                </div>
              </div>

              {/* 고령화 그래프 */}
              <div className="bg-slate-50 p-5 rounded-xl border border-slate-200/60 flex flex-col justify-between shadow-sm">
                <div className="mb-2">
                  <h4 className="text-xs md:text-sm font-bold text-slate-800 flex items-center gap-1.5">
                    <TrendingUp className="w-4 h-4 text-indigo-600" />
                    노인인구 비중(%) 및 노년부양비(명) 추이
                  </h4>
                  <p className="text-[11px] text-slate-500 mt-0.5">2020년부터 2070년까지의 대한민국 고령화 폭증 속도</p>
                </div>
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={populationData} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip formatter={(value, name) => [value, name === "ratio" ? "65세이상 비율 (%)" : "노년부양비 (명)"]} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Line type="monotone" dataKey="ratio" stroke="#4f46e5" strokeWidth={3} name="ratio" />
                      <Line type="monotone" dataKey="support" stroke="#dc2626" strokeWidth={3} name="support" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <p className="text-[10px] text-center text-slate-450 mt-2 font-medium">출처: 통계청 장래인구추계 가정 기반</p>
              </div>
            </div>
          </div>
        )}

        {/* 화면 2. 국민연금의 장기 위험 */}
        {subStep === 2 && (
          <div className="space-y-6" id="risk-screen">
            <div className="bg-rose-50 rounded-xl p-5 border border-rose-100">
              <h3 className="text-base md:text-lg font-bold text-rose-900 flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-rose-600" />
                2. 국민연금 통장 잔고가 '0원'이 된다면? (재정 고갈 위기)
              </h3>
              <p className="text-xs md:text-sm text-slate-600 mt-1 leading-relaxed">
                현재의 국민연금 제도(보험료는 소득의 9%, 은퇴 후 받는 돈 비율은 40~43%)를 아무 대책 없이 장기간 그대로 지속할 경우 일어날 미래의 타임라인입니다.
              </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              {/* 위험 수치 카드 리스트 */}
              <div className="space-y-3">
                <h4 className="text-sm font-bold text-slate-800 border-b pb-2">🚨 현행 제도 유지 시 일어날 미래 타임라인</h4>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
                    <p className="text-xs text-slate-500 font-semibold">지출이 수입보다 많아지는 해</p>
                    <p className="text-base md:text-lg font-extrabold text-rose-600 mt-1">2027년 (적자 시작)</p>
                    <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">매년 걷는 보험료보다 은퇴자분들께 줘야 할 연금액이 더 커지기 시작합니다.</p>
                  </div>
                  
                  <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
                    <p className="text-xs text-slate-500 font-semibold">투자 이자로도 못 메우는 해</p>
                    <p className="text-base md:text-lg font-extrabold text-rose-600 mt-1">2048년</p>
                    <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">연금 기금을 굴려서 번 이자로도 연도별 적자를 채울 수 없어, 쌓아둔 저금통 돈을 본격적으로 깨서 씁니다.</p>
                  </div>

                  <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
                    <p className="text-xs text-slate-500 font-semibold">연금 통장 잔고가 바닥나는 해</p>
                    <p className="text-base md:text-lg font-extrabold text-rose-700 mt-1">2065년 (기금 완기고갈)</p>
                    <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">연금 저금통에 모아둔 돈이 '0원'이 됩니다. (투자를 아주 잘해 연 5.5% 수익을 내더라도 2071년이면 다 써버립니다.)</p>
                  </div>

                  <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
                    <p className="text-xs text-slate-500 font-semibold">고갈 직후 청년들이 내야 할 연금비율</p>
                    <p className="text-base md:text-lg font-extrabold text-rose-800 mt-1">월급의 39.2% (2079년)</p>
                    <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">저금통에 돈이 전혀 없기 때문에, 그해 은퇴자분들께 연금을 드리려면 일하는 청년들은 월급의 약 40%를 연금으로 내야 합니다.</p>
                  </div>
                </div>

                <div className="p-4 bg-amber-50 border border-amber-150 rounded-xl text-amber-900 text-xs md:text-sm font-medium">
                  <strong>💡 부족한 돈을 그냥 국가 세금으로 땜빵하면?</strong> 보험료를 올리지 않고 부족한 돈을 전부 나라 세금으로 다 메우려면, 미래에는 대한민국 총 국가 예산의 상당 부분을 연금을 채워 넣는 데만 쏟아부어야 합니다. 다른 복지나 청년 지원 사업을 할 돈이 완전히 사라지는 큰 위기가 생깁니다.
                </div>
              </div>

              {/* 기금 소모 추이 시각화 */}
              <div className="bg-slate-50 p-5 rounded-xl border border-slate-200/60 flex flex-col justify-between shadow-sm">
                <div className="mb-2">
                  <h4 className="text-xs md:text-sm font-bold text-slate-800 flex items-center gap-1.5">
                    <Landmark className="w-4 h-4 text-rose-600" />
                    기금 적립금 규모 추이 전망 (단위: 조 원)
                  </h4>
                  <p className="text-[11px] text-slate-500 mt-0.5">2025년부터 2065년 고갈 시점까지의 기금 피크 및 수직 낙하 곡선</p>
                </div>
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={fundTrendData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                      <defs>
                        <linearGradient id="colorFund" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#dc2626" stopOpacity={0.2}/>
                          <stop offset="95%" stopColor="#dc2626" stopOpacity={0}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip formatter={(value: any) => [`${value}조 원`, "기금 잔액"]} />
                      <Area type="monotone" dataKey="fund" stroke="#dc2626" strokeWidth={3} fillOpacity={1} fill="url(#colorFund)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <p className="text-[10px] text-center text-slate-400 mt-2">※ 2065년 전후 완기고갈 이후 마이너스 재정 영역으로 진입</p>
              </div>
            </div>
          </div>
        )}

        {/* 화면 3. 기초연금의 문제 */}
        {subStep === 3 && (
          <div className="space-y-6" id="basic-pension-screen">
            <div className="bg-amber-50 rounded-xl p-5 border border-amber-100">
              <h3 className="text-base md:text-lg font-bold text-amber-900 flex items-center gap-2">
                <Landmark className="w-5 h-5 text-amber-600" />
                3. 노후 빈곤 해결과 자녀들의 세금 부담 사이의 저울질
              </h3>
              <p className="text-xs md:text-sm text-slate-600 mt-1 leading-relaxed">
                기초연금은 자신이 매달 내던 보험료가 아니라, 100% 우리가 내는 '세금'으로 충당됩니다. OECD에서 가장 심각한 수준인 노인 빈곤 문제를 풀려면 어르신들께 연금을 많이 드려야 하지만, 그만큼 우리 자녀들이 미래에 내야 할 세금 부담도 덩달아 불어나는 고민이 있습니다.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* 기초연금의 주요 지표 */}
              <div className="space-y-4 p-5 bg-slate-50 rounded-xl border border-slate-200">
                <h4 className="text-xs md:text-sm font-bold text-slate-850 border-b pb-2">📌 꼭 알아야 할 우리나라 노후 빈곤과 기초연금 실태</h4>
                <ul className="space-y-3.5 text-xs md:text-sm text-slate-600">
                  <li className="flex items-start gap-2.5">
                    <span className="w-2 h-2 rounded-full bg-amber-500 mt-2 flex-shrink-0"></span>
                    <div className="leading-relaxed">
                      <strong>심각한 노인 빈곤율:</strong> 우리나라 노인 10명 중 3.5명(<span className="text-rose-600 font-extrabold">35.9%</span>)은 중위소득의 절반도 못 버는 아주 어려운 상황으로, OECD 국가 중 부동의 1위입니다.
                    </div>
                  </li>
                  <li className="flex items-start gap-2.5">
                    <span className="w-2 h-2 rounded-full bg-amber-500 mt-2 flex-shrink-0"></span>
                    <div className="leading-relaxed">
                      <strong>지금 드리는 기초연금액:</strong> 물가상승을 반영하여 매달 평균 약 <span className="font-bold text-slate-800">34.3만 원</span>을 드리고 있습니다.
                    </div>
                  </li>
                  <li className="flex items-start gap-2.5">
                    <span className="w-2 h-2 rounded-full bg-amber-500 mt-2 flex-shrink-0"></span>
                    <div className="leading-relaxed">
                      <strong>지급 대상 범위:</strong> 65세 이상 어르신들 중 재산과 소득을 따져 형편이 비교적 어려운 <span className="font-bold text-slate-800">하위 70%</span>분들께 드립니다.
                    </div>
                  </li>
                  <li className="flex items-start gap-2.5">
                    <span className="w-2 h-2 rounded-full bg-indigo-600 mt-2 flex-shrink-0"></span>
                    <div className="leading-relaxed">
                      <strong>개혁안의 공통 약속:</strong> 더 효율적이고 합리적인 지급을 위해 대상을 '중위소득 100% 이하 어르신'으로 분명하게 정하고, 앞으로는 물가가 오르는 만큼만 연금을 올려서 세금이 너무 급속하게 불어나는 것을 제어합니다. (받기 시작하는 나이는 만 65세를 유지합니다)
                    </div>
                  </li>
                </ul>
              </div>

              {/* 핵심 토론 딜레마 요약 */}
              <div className="space-y-4 p-5 bg-amber-50/50 rounded-xl border border-amber-100">
                <h4 className="text-xs md:text-sm font-bold text-amber-900 border-b border-amber-200 pb-2">⚖️ 숙의실험에서 함께 고민해야 할 문제</h4>
                <div className="space-y-3 text-xs md:text-sm text-slate-750">
                  <div className="p-3 bg-white rounded-xl border border-amber-100 shadow-sm">
                    <p className="font-bold text-amber-900">1. 똑같이 나눠주기 vs 어려운 이웃 더 두텁게 돕기</p>
                    <p className="text-slate-600 mt-1 leading-relaxed text-xs">모든 어르신께 똑같이 40만 원을 드리는 것이 공평할까요, 아니면 형편이 정말 어려운 분께 50만 원을 드리는 대신 살만한 분께는 20만 원을 드려 세금을 더 가치 있게 쓰는 게 맞을까요?</p>
                  </div>
                  <div className="p-3 bg-white rounded-xl border border-amber-100 shadow-sm">
                    <p className="font-bold text-amber-900">2. 다가올 세금 폭탄을 막기 위한 '연금 저축'</p>
                    <p className="text-slate-600 mt-1 leading-relaxed text-xs">어차피 미래 세금으로 메울 연금이라면, 지금 나라 재정에 여유가 있을 때 미리 60조 원 정도를 떼어 저축 기금으로 만들고 투자해 두는 게 미래 자녀들의 세금 폭탄을 덜어주는 좋은 방법이 될 수 있을까요?</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 진행 통제 영역 */}
        <div className="mt-8 flex justify-between items-center border-t border-slate-200 pt-6">
          <button
            id="btn-baseline-prev"
            disabled={subStep === 1}
            onClick={() => setSubStep((prev) => Math.max(1, prev - 1))}
            className={`py-2.5 px-4 rounded-xl text-xs md:text-sm font-bold border transition-all ${
              subStep === 1
                ? "border-slate-150 text-slate-300 cursor-not-allowed bg-slate-50"
                : "border-slate-250 text-slate-700 hover:bg-slate-100 cursor-pointer shadow-sm"
            }`}
          >
            이전 기준정보
          </button>

          <p className="text-xs text-slate-400 font-semibold hidden sm:block">
            공통 기준정보 제공 및 사회적 딜레마 인식 단계 ({subStep} / 3)
          </p>

          {subStep < 3 ? (
            <button
              id="btn-baseline-next-sub"
              onClick={() => setSubStep((prev) => Math.min(3, prev + 1))}
              className="py-2.5 px-5 bg-indigo-600 text-white rounded-xl text-xs md:text-sm font-bold hover:bg-indigo-700 hover:shadow transition-all flex items-center gap-1 cursor-pointer"
            >
              다음 기준정보
              <ArrowRight className="w-4 h-4" />
            </button>
          ) : (
            <button
              id="btn-baseline-complete"
              onClick={onNext}
              className="py-2.5 px-6 bg-indigo-600 text-white rounded-xl text-xs md:text-sm font-bold hover:bg-indigo-700 shadow-sm transition-all flex items-center gap-1.5 cursor-pointer"
            >
              2단계: 전문가 개혁안 설명으로 이동
              <ArrowRight className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
