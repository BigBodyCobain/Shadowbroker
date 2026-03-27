'use client';

import React, { useState } from 'react';
import { ChevronLeft, Briefcase, CheckCircle, Clock } from 'lucide-react';

interface Job {
  id: string;
  title: string;
  description: string;
  reward: number;
  status: 'Open' | 'In Progress' | 'Completed';
  timeLimit: string;
}

const MOCK_JOBS: Job[] = [
  {
    id: 'JOB-901',
    title: 'Host Routing Node',
    description: 'Maintain 99.9% uptime for a Tier-2 mesh routing node for 24 hours. Bandwidth requirement: 10Gbps minimum.',
    reward: 300,
    status: 'Open',
    timeLimit: '24h'
  },
  {
    id: 'JOB-902',
    title: 'Find Prediction Market Source',
    description: 'Provide an unassailable, cryptographically signed news source confirming the outcome of the "Arasaka Merger" market.',
    reward: 500,
    status: 'Open',
    timeLimit: '12h'
  },
  {
    id: 'JOB-903',
    title: 'Smart Contract Audit',
    description: 'Find interesting things a blockchain might need fulfilled. Specifically looking for reentrancy vulnerabilities in the new Credits staking pool.',
    reward: 5000,
    status: 'Open',
    timeLimit: '72h'
  },
  {
    id: 'JOB-904',
    title: 'Data Courier to Sector 4',
    description: 'Physically transport an encrypted drive to a dead drop in Sector 4. High risk, high reward. No questions asked.',
    reward: 1500,
    status: 'Open',
    timeLimit: '4h'
  }
];

export default function WorkView({ onBack }: { onBack: () => void }) {
  const [jobs, setJobs] = useState<Job[]>(MOCK_JOBS);

  const handleAccept = (id: string) => {
    setJobs(jobs.map(job => job.id === id ? { ...job, status: 'In Progress' } : job));
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-800 pb-4 mb-4 shrink-0">
        <button
          onClick={onBack}
          className="flex items-center text-cyan-500 hover:text-cyan-400 transition-all uppercase text-xs tracking-widest border border-cyan-900/50 px-3 py-1 bg-cyan-900/10 hover:bg-cyan-900/30 hover:border-cyan-500/50 mb-4"
        >
          <ChevronLeft size={14} className="mr-1" />
          RETURN TO MAIN
        </button>
        <h1 className="text-2xl font-bold text-cyan-400 uppercase tracking-widest flex items-center">
          <Briefcase className="mr-2 text-cyan-400" />
          NETWORK WORK & BOUNTIES
        </h1>
        <p className="text-gray-500 text-sm mt-1">Earn Credits and Common Rep by fulfilling network contracts.</p>
      </div>

      {/* Jobs List */}
      <div className="flex-1 overflow-y-auto pr-2 space-y-4 pb-4">
        {jobs.map(job => (
          <div key={job.id} className="border border-gray-800 bg-gray-900/20 p-4 hover:border-gray-700 transition-colors">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs text-gray-500 uppercase tracking-widest">CONTRACT ID: {job.id}</span>
              <span className={`text-xs font-bold px-2 py-1 border ${
                job.status === 'Open' ? 'text-green-400 border-green-900/50 bg-green-900/20' :
                job.status === 'In Progress' ? 'text-cyan-400 border-cyan-900/50 bg-cyan-900/20' :
                'text-cyan-400 border-cyan-900/50 bg-cyan-900/20'
              }`}>
                {job.status}
              </span>
            </div>

            <h2 className="text-lg text-gray-300 font-bold mb-2">{job.title}</h2>
            <p className="text-sm text-gray-400 mb-4 leading-relaxed">{job.description}</p>

            <div className="flex items-center justify-between border-t border-gray-800 pt-3 mt-2">
              <div className="flex gap-4 text-sm">
                <span className="text-gray-300 font-bold flex items-center">
                  REWARD: <span className="text-green-400 ml-2">{job.reward} CREDITS</span>
                </span>
                <span className="text-gray-500 flex items-center">
                  <Clock size={14} className="mr-1" /> {job.timeLimit}
                </span>
              </div>
              {job.status === 'Open' && (
                <button
                  onClick={() => handleAccept(job.id)}
                  className="flex items-center px-4 py-2 bg-gray-900/50 border border-gray-800 text-cyan-400 hover:bg-gray-800 hover:text-cyan-300 transition-colors text-xs uppercase tracking-widest"
                >
                  <CheckCircle size={14} className="mr-2" /> ACCEPT CONTRACT
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
