import React from 'react';
import { CHAT_WORKFLOW_NODE_LABEL } from '../../../shared/enum';
import type { ChatNodeStatus } from '../../../shared/types';
import './HolographicNode.css';

interface HolographicNodeProps {
  type: 'start' | 'end' | 'normal' | 'condition';
  nodeType: string;
  status: ChatNodeStatus | 'pending';
  isActive: boolean;
  onToggleAR?: (e: React.MouseEvent) => void;
  interactionId?: string;
}

export const HolographicNode: React.FC<HolographicNodeProps> = ({
  type,
  nodeType,
  status,
  isActive,
  onToggleAR
}) => {
  // Determine Label
  let label = nodeType;
  if (type === 'start') label = 'INGRESS';
  else if (type === 'end') label = 'TERMINATE';
  else if (CHAT_WORKFLOW_NODE_LABEL[nodeType as keyof typeof CHAT_WORKFLOW_NODE_LABEL]) {
      label = CHAT_WORKFLOW_NODE_LABEL[nodeType as keyof typeof CHAT_WORKFLOW_NODE_LABEL];
  }

  // Map backend status to visual status
  let visualStatus = 'pending';
  if (status === 'running') visualStatus = 'running';
  else if (status === 'succeeded' || status === 'not_entered_by_condition') visualStatus = 'success';
  else if (status === 'failed' || status === 'degraded') visualStatus = 'failed';

  // Specific classes
  const classes = [
      'holographic-node-container',
      `node-type-${type}`,
      `status-${visualStatus}`,
      isActive ? 'is-active' : ''
  ].filter(Boolean).join(' ');

  return (
    <div className={classes} data-node-type={nodeType}>
      {/* Geometries based on type */}
      {type === 'start' || type === 'end' ? (
          <div className="node-stargate">
              <div className="stargate-ring"></div>
              <div className="stargate-core"></div>
              <span className="node-label">{label}</span>
          </div>
      ) : type === 'condition' ? (
          <div className="node-diamond">
              <div className="diamond-shape"></div>
              <div className="diamond-content">
                  <span className="node-label">{label}</span>
              </div>
              <div className="ar-trigger" onClick={onToggleAR} title="View Details">
                  <span className="trigger-icon">◬</span>
              </div>
          </div>
      ) : (
          <div className="node-card">
              <div className="card-glass"></div>
              <div className="card-content">
                  <span className="node-label">{label}</span>
              </div>
              <div className="ar-trigger" onClick={onToggleAR} title="View Trace">
                  <span className="trigger-icon">[T]</span>
              </div>
          </div>
      )}
      
      {/* Glitch overlay for failed state */}
      {visualStatus === 'failed' && (
          <div className="glitch-overlay"></div>
      )}
    </div>
  );
};
