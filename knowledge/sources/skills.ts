export interface SkillCategory {
  id: string;
  name: string;
  featured: boolean;
  skills: string[];
}

// Grouped by capability, tools as evidence (M2-04). Sources for the skills added in M2:
// docs/plans/2026-10-18-M2-positioning.md § Skills.
export const skillCategories: SkillCategory[] = [
  {
    id: 'process',
    name: 'Process & delivery',
    featured: true,
    skills: [
      'Requirements',
      'Specs and decision ledgers',
      'AGILE/Scrum',
      'Linear',
      'Project management',
      'Team onboarding',
      'User-driven design',
    ],
  },
  {
    id: 'systems',
    name: 'Systems & architecture',
    featured: false,
    skills: [
      'Multi-tenant architecture',
      'ETL pipelines',
      'RESTful APIs',
      'OAuth 2.0',
      'Webhooks',
      'Pipedream',
      'n8n',
      'Zapier',
      'Self-hosted infrastructure',
      'Docker',
      'Agent orchestration',
      'Agentic AI',
    ],
  },
  {
    id: 'build',
    name: 'Build',
    featured: false,
    skills: [
      'TypeScript',
      'JavaScript',
      'Python',
      'PowerShell',
      'Java',
      'C/C++',
      'Ruby',
      'R',
      'React',
      'Next.js',
      'React Native',
      'Expo',
      'Tailwind CSS',
      'Framer Motion',
      'Node.js',
      'Flask',
      'Ruby on Rails',
      'PostgreSQL',
      'Supabase',
      'Supabase Edge Functions',
      'MongoDB',
      'SQLite',
      'Claude Code',
      'AI-assisted development',
    ],
  },
  {
    id: 'operate',
    name: 'Operate & verify',
    featured: false,
    skills: [
      'Test-driven development',
      'GitHub Actions',
      'restic',
      'Private networking',
      'Git',
      'Vercel',
      'Linux CLI',
      'WSL',
    ],
  },
];
