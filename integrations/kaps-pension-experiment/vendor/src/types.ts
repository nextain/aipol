export type AgeGroup = "20-29" | "30-39" | "40-49" | "50-59" | "60-69" | "70+";

export type IncomeLevel = "under_2m" | "2m_4m" | "4m_6m" | "6m_8m" | "over_8m";

export type JobType = "regular" | "temporary" | "self_employed" | "unemployed" | "retired";

export interface UserProfile {
  ageGroup: AgeGroup | "";
  incomeLevel: IncomeLevel | "";
  jobType: JobType | "";
  isMember: "yes" | "no" | "";
  retireAge: number;
  basicPensionEligible: "yes" | "no" | "maybe" | "";
}

export interface PerceptionAnswers {
  q1: number; //지속성
  q2: number; //운용수익률
  q3: number; //일반재정투입
  q4: number; //수급연령상향
  q5: number; //기초연금보편
  q6: number; //기초연금선별
  q7: number; //미래기금적립
  q8: number; //미래세대배려
}

export interface KnowledgeAnswers {
  premiumRate: string; // 국민연금 보험료율
  replacementRate: string; // 국민연금 소득대체율
  fundingDifference: string; // 재원 차이
  fundMeaning: string; // 기금의 의미
  basicTarget: string; // 기초연금 수급대상
}

export type NationalOption = "N-A" | "N-B" | "N-C" | "NONE" | "UNDECIDED" | "";
export type BasicOption = "B-A" | "B-B" | "B-C" | "NONE" | "UNDECIDED" | "";
export type IntegratedOption = "P1" | "P2" | "P3" | "NONE" | "UNDECIDED" | "";

export interface VoteData {
  nationalPension: NationalOption;
  nationalConfidence: number; // 0-100
  nationalFairness: number; // 1-7
  nationalBenefit: number; // 1-7
  nationalFeasibility: number; // 1-7
  nationalReason: string; // 고려기준

  basicPension: BasicOption;
  basicConfidence: number;
  basicFairness: number;
  basicBenefit: number;
  basicFeasibility: number;
  basicReason: string;

  integratedPackage: IntegratedOption;
  acceptAsGovernment: number; // 1-7
  acceptForSociety: number; // 1-7
  generationalFairness: number; // 1-7
  poorProtection: number; // 1-7
  sustainability: number; // 1-7
  riskManageable: number; // 1-7

  // 재정충돌 완화 선택 (N-B + B-C 조합 시 발생)
  conflictResolution?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "model";
  text: string;
  timestamp: Date;
}
