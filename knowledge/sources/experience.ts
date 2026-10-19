export interface Role {
  title: string;
  company: string;
  period: string;
  bullets: string[];
  type: 'work' | 'education';
}

export const roles: Role[] = [
  {
    title: 'Full-Stack Software Engineer',
    company: 'MAXX Potential',
    period: 'February 2026 – Present',
    type: 'work',
    bullets: [
      'Diagnosed a QA/Engineering issue-tracking bottleneck and moved the team to Linear with an AI-agent workflow: 2× sprint throughput and ~80% less bug-filing time.',
      'Served as de facto project manager on a client engagement.',
      'Updated the org\'s Foundational Capability Patterns for AI-assisted rapid prototyping: solution tiers and citizen vs. professional development pathways.',
      'Bootstrapped git-tracked database migrations and onboarded the team to them.',
      'Chose Linear partly for its MCP server, so the team\'s Claude Code workflow could fetch and update issues directly; bug filing and triage, including duplicate detection, became automated.',
      'Built full-stack React Native features for a paint-estimator app, establishing development paradigms and reusable modules from go-live.',
    ],
  },
  {
    title: 'Founding Full-Stack Software Engineer',
    company: 'Builder Clarity',
    period: 'March 2025 – November 2025',
    type: 'work',
    bullets: [
      'First engineer hired. Architected a multi-tenant integration platform that eliminated per-client buildouts — scaling to 3 clients and cutting onboarding from ~2 days to ~6 hours.',
      'Integrated CRM, VoIP, and internal systems via secure data pipelines (GoHighLevel ↔ JobTread, RingCentral ↔ JobTread), eliminating manual data entry and saving ~8 hrs/week per client.',
      'Built and maintained ETL pipelines ingesting and normalizing data from 4+ sources into Postgres for a previously fragmented dataset.',
      'Introduced Agile/Scrum in Linear for stakeholder visibility, and led the technical migration from Zapier to n8n and Pipedream.',
    ],
  },
  {
    title: 'AI Workflow Engineer',
    company: 'Tahoma Films',
    period: 'February 2025',
    type: 'work',
    bullets: [
      'Refined AI image generation workflows using Invoke.AI (control nets, denoising, regional guidance).',
      'Trained LoRAs for art style and character consistency across generated images.',
    ],
  },
  {
    title: 'Snowboard Coach',
    company: 'High Cascade Snowboard Camp',
    period: 'Summers 2023 & 2024',
    type: 'work',
    bullets: [
      'Mentored 12–18-year-old snowboarders; designed targeted drills, prioritized safe progression.',
      'Coaching approach — clear instruction, patient feedback, tailored communication — translates directly to how I collaborate and communicate in engineering teams.',
    ],
  },
];

export interface Education {
  degree: string;
  institution: string;
  period: string;
  honors: string[];
  coursework: string[];
}

export const education: Education = {
  degree: 'B.S. Computer Science, Visual & Media Studies Minor',
  institution: 'Duke University',
  period: 'Graduated December 2024',
  honors: ['George Scholar', 'Duke True North Leadership Program'],
  coursework: [
    'Algorithm Design & Analysis',
    'Database Systems',
    'Computer Security',
    'Server-side Web Apps',
    'Data Science',
    'AGILE',
  ],
};
