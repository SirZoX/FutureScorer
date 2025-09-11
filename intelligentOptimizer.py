"""
Intelligent Parameter Optimizer - Auto-optimization system for FutureScorer
Analyzes closed positions to automatically improve trading parameters
"""

import json
import os
import time
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import gvars
import configManager
from logManager import messages


class IntelligentParameterOptimizer:
    """
    Intelligent system that learns from closed positions to optimize trading parameters
    """
    
    def __init__(self):
        # Configuration
        self.minimumSampleSize = 50  # Minimum closed positions before optimization
        self.optimizationFrequency = 10  # Optimize every N positions after minimum
        self.maxChangePerOptimization = 0.1  # Maximum 10% parameter change per iteration
        
        # Initialize paths
        self.learningDbPath = os.path.join(gvars.dataPath, "learningDatabase.json")
        
        # Load database after setting configuration
        self.learningDb = self.loadLearningDatabase()
        
        # Parameter safety limits
        self.parameterLimits = {
            "scoreThreshold": {"min": 0.2, "max": 0.8},
            "tolerancePct": {"min": 0.003, "max": 0.015},
            "minTouches": {"min": 2, "max": 6},
            "scoringWeights": {
                "distance": {"min": 0.1, "max": 0.4},
                "volume": {"min": 0.2, "max": 0.5},
                "momentum": {"min": 0.1, "max": 0.4},
                "touches": {"min": 0.1, "max": 0.4}
            }
        }
    
    def loadLearningDatabase(self) -> Dict:
        """Load existing learning database or create new one"""
        if os.path.exists(self.learningDbPath):
            try:
                with open(self.learningDbPath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    messages(f"[OPTIMIZER] Loaded learning database with {data.get('totalClosedPositions', 0)} positions", console=0, log=1, telegram=0)
                    return data
            except Exception as e:
                messages(f"[OPTIMIZER] Error loading learning database: {e}", console=0, log=1, telegram=0)
        
        # Create new database
        newDb = {
            "totalClosedPositions": 0,
            "learningEnabled": True,
            "minimumSampleSize": self.minimumSampleSize,
            "lastOptimization": None,
            "optimizationHistory": [],
            "positionOutcomes": []
        }
        self.saveLearningDatabase(newDb)
        messages("[OPTIMIZER] Created new learning database", console=0, log=1, telegram=0)
        return newDb
    
    def saveLearningDatabase(self, data: Dict = None):
        """Save learning database to file"""
        if data is None:
            data = self.learningDb
            
        try:
            os.makedirs(os.path.dirname(self.learningDbPath), exist_ok=True)
            with open(self.learningDbPath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messages(f"[OPTIMIZER] Error saving learning database: {e}", console=0, log=1, telegram=0)
    
    def analyzeClosedPosition(self, positionData: Dict, outcome: Dict):
        """
        Analyze a closed position and add to learning database
        
        Args:
            positionData: Original position data from openedPositions.json
            outcome: Result data (profit/loss, time, reason, etc.)
        """
        try:
            # Extract entry parameters from position or derive from logs
            entryParams = self.extractEntryParameters(positionData)
            
            # Create learning record
            learningRecord = {
                "id": positionData.get("opportunityId", "unknown"),
                "pair": positionData.get("symbol", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "entryParams": entryParams,
                "outcome": outcome,
                "marketConditions": self.captureMarketConditions(positionData)
            }
            
            # Add to database
            self.learningDb["positionOutcomes"].append(learningRecord)
            self.learningDb["totalClosedPositions"] += 1
            
            # Save database
            self.saveLearningDatabase()
            
            messages(f"[OPTIMIZER] Recorded position outcome: {positionData.get('symbol')} - {outcome.get('result', 'unknown')}", 
                    console=0, log=1, telegram=0)
            
            # Check if we should optimize
            if self.shouldOptimize():
                self.runOptimization()
                
        except Exception as e:
            messages(f"[OPTIMIZER] Error analyzing closed position: {e}", console=0, log=1, telegram=0)
    
    def extractEntryParameters(self, positionData: Dict) -> Dict:
        """Extract the parameters that were used for entry decision"""
        # Try to get from selectionLog first using opportunityId
        try:
            opportunityId = positionData.get("opportunityId", "")
            if opportunityId:
                # Search selectionLog for this ID
                selectionLogPath = os.path.join(gvars.logsFolder, "selectionLog.csv")
                if os.path.exists(selectionLogPath):
                    import csv
                    with open(selectionLogPath, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f, delimiter=';')
                        for row in reader:
                            if row.get('id') == opportunityId:
                                # Found the original entry parameters
                                return {
                                    "score": float(row.get('score', 0)),
                                    "scoreThreshold": float(row.get('scoreThreshold', 0.4)),
                                    "tolerancePct": float(row.get('tolerancePct', 0.0075)),
                                    "minTouches": int(row.get('minTouches', 3)),
                                    "distancePct": float(row.get('distancePct', 0)),
                                    "volumeRatio": float(row.get('volumeRatio', 0)),
                                    "momentum": float(row.get('momentum', 0)),
                                    "touchesCount": int(row.get('touchesCount', 0)),
                                    "leverage": int(row.get('leverage', 35)),
                                    "tp1": float(row.get('tp1', 0.30)),
                                    "sl1": float(row.get('sl1', 0.40))
                                }
        except Exception as e:
            messages(f"[OPTIMIZER] Error reading selectionLog for {opportunityId}: {e}", console=0, log=1, telegram=0)
        
        # Fallback: use current config values
        currentConfig = configManager.config
        return {
            "scoreThreshold": currentConfig.get("scoreThreshold", 0.4),
            "tolerancePct": currentConfig.get("tolerancePct", 0.0075),
            "minTouches": currentConfig.get("minTouches", 3),
            "scoringWeights": currentConfig.get("scoringWeights", {}),
            "topCoinsPctAnalyzed": currentConfig.get("topCoinsPctAnalyzed", 50),
            "leverage": currentConfig.get("leverage", 35),
            "tp1": currentConfig.get("tp1", 0.30),
            "tp2": currentConfig.get("tp2", 0.50),
            "sl1": currentConfig.get("sl1", 0.40)
        }
    
    def captureMarketConditions(self, positionData: Dict) -> Dict:
        """Capture market conditions at time of entry"""
        return {
            "side": positionData.get("side", "unknown"),
            "leverage": positionData.get("leverage", 0),
            "openPrice": positionData.get("openPrice", 0),
            "timestamp": positionData.get("timestamp", "unknown")
        }
    
    def shouldOptimize(self) -> bool:
        """Check if we should run parameter optimization"""
        total = self.learningDb["totalClosedPositions"]
        
        if not self.learningDb.get("learningEnabled", True):
            return False
            
        if total < self.minimumSampleSize:
            return False
            
        # After minimum sample, optimize every N positions
        return total % self.optimizationFrequency == 0
    
    def runOptimization(self):
        """Run the parameter optimization process"""
        try:
            messages(f"🧠 [OPTIMIZER] Starting optimization with {self.learningDb['totalClosedPositions']} positions", 
                    console=1, log=1, telegram=1)
            
            # Calculate new optimal parameters
            newParams = self.calculateOptimalParameters()
            
            if newParams:
                # Update configuration
                self.updateConfiguration(newParams)
                
                # Record optimization in history
                self.recordOptimization(newParams)
                
                messages(f"🎯 [OPTIMIZER] Optimization completed: {newParams}", 
                        console=1, log=1, telegram=1)
            else:
                messages("[OPTIMIZER] No parameter changes needed", console=1, log=1, telegram=0)
                
        except Exception as e:
            messages(f"[OPTIMIZER] Error during optimization: {e}", console=0, log=1, telegram=0)
    
    def calculateOptimalParameters(self) -> Optional[Dict]:
        """Calculate new optimal parameters based on learning data"""
        positions = self.learningDb["positionOutcomes"]
        
        if len(positions) < self.minimumSampleSize:
            return None
        
        # Separate profitable and losing positions
        profitable = [p for p in positions if p["outcome"].get("result") == "profit"]
        losses = [p for p in positions if p["outcome"].get("result") == "loss"]
        
        if len(profitable) == 0 or len(losses) == 0:
            messages("[OPTIMIZER] Need both profitable and losing positions for optimization", 
                    console=0, log=1, telegram=0)
            return None
        
        # Calculate win rate
        winRate = len(profitable) / len(positions)
        messages(f"[OPTIMIZER] Current win rate: {winRate:.2%} ({len(profitable)}/{len(positions)})", 
                console=1, log=1, telegram=0)
        
        newParams = {}
        
        # Optimize scoreThreshold
        newThreshold = self.optimizeScoreThreshold(profitable, losses)
        if newThreshold:
            newParams["scoreThreshold"] = newThreshold
        
        # TODO: Add more parameter optimizations
        # - tolerancePct
        # - scoringWeights
        # - minTouches
        
        return newParams if newParams else None
    
    def optimizeScoreThreshold(self, profitable: List, losses: List) -> Optional[float]:
        """Optimize the score threshold parameter"""
        try:
            # Get current threshold
            currentThreshold = configManager.config.get("scoreThreshold", 0.4)
            
            # Extract scores from profitable and losing positions
            profitScores = []
            lossScores = []
            
            for p in profitable:
                if "score" in p["entryParams"]:
                    profitScores.append(p["entryParams"]["score"])
            
            for p in losses:
                if "score" in p["entryParams"]:
                    lossScores.append(p["entryParams"]["score"])
            
            if not profitScores or not lossScores:
                return None
            
            # Find threshold that maximizes quality
            # Use 20th percentile of profitable scores (80% of profits above this)
            profitMin = np.percentile(profitScores, 20)
            
            # Calculate potential new threshold
            newThreshold = max(profitMin, currentThreshold * 1.02)  # Conservative 2% increase
            
            # Apply safety limits
            limits = self.parameterLimits["scoreThreshold"]
            newThreshold = max(limits["min"], min(limits["max"], newThreshold))
            
            # Apply maximum change limit
            maxChange = currentThreshold * self.maxChangePerOptimization
            if abs(newThreshold - currentThreshold) > maxChange:
                if newThreshold > currentThreshold:
                    newThreshold = currentThreshold + maxChange
                else:
                    newThreshold = currentThreshold - maxChange
            
            # Only return if change is significant (>1%)
            if abs(newThreshold - currentThreshold) / currentThreshold > 0.01:
                messages(f"[OPTIMIZER] Score threshold: {currentThreshold:.3f} → {newThreshold:.3f}", 
                        console=1, log=1, telegram=0)
                return round(newThreshold, 3)
            
            return None
            
        except Exception as e:
            messages(f"[OPTIMIZER] Error optimizing score threshold: {e}", console=0, log=1, telegram=0)
            return None
    
    def updateConfiguration(self, newParams: Dict):
        """Update the configuration file with new parameters"""
        try:
            # Update in-memory config
            for param, value in newParams.items():
                configManager.config[param] = value
            
            # Save to file
            configManager.saveConfig()
            
            messages(f"[OPTIMIZER] Configuration updated with new parameters", console=1, log=1, telegram=0)
            
        except Exception as e:
            messages(f"[OPTIMIZER] Error updating configuration: {e}", console=0, log=1, telegram=0)
    
    def recordOptimization(self, newParams: Dict):
        """Record optimization in history"""
        optimizationRecord = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "totalPositions": self.learningDb["totalClosedPositions"],
            "parameters": newParams,
            "winRate": self.calculateCurrentWinRate()
        }
        
        self.learningDb["optimizationHistory"].append(optimizationRecord)
        self.learningDb["lastOptimization"] = optimizationRecord["timestamp"]
        self.saveLearningDatabase()
    
    def calculateCurrentWinRate(self) -> float:
        """Calculate current win rate from recent positions"""
        positions = self.learningDb["positionOutcomes"]
        if not positions:
            return 0.0
        
        profitable = len([p for p in positions if p["outcome"].get("result") == "profit"])
        return profitable / len(positions)
    
    def loadHistoricalClosedPositions(self):
        """
        Load historical closed positions and add them to learning database
        This is useful for bootstrapping the learning system with existing data
        """
        try:
            closedPositionsPath = os.path.join(gvars.jsonFolder, "closedPositions.json")
            if not os.path.exists(closedPositionsPath):
                messages("[OPTIMIZER] No historical closed positions file found", console=0, log=1, telegram=0)
                return 0
            
            with open(closedPositionsPath, 'r', encoding='utf-8') as f:
                closedPositions = json.load(f)
            
            if not closedPositions:
                return 0
            
            addedCount = 0
            existingIds = {p.get('id', '') for p in self.learningDb.get('positionOutcomes', [])}
            
            for key, pos in closedPositions.items():
                # Check if we already have this position in learning database
                posId = pos.get('opportunityId', key)
                if posId in existingIds:
                    continue
                
                # Convert to learning format
                outcome = {
                    "result": "profit" if pos.get("pnlQuote", 0) > 0 else "loss" if pos.get("pnlQuote", 0) < 0 else "breakeven",
                    "profitPct": pos.get("pnlPct", 0) / 100.0,  # Convert to decimal
                    "profitUsdt": pos.get("pnlQuote", 0),
                    "closeReason": pos.get("closeReason", "unknown"),
                    "timeToClose": None,  # TODO: Calculate if we have timestamps
                    "actualBounce": None,
                    "bounceAccuracy": None
                }
                
                # Add to learning database
                self.analyzeClosedPosition(pos, outcome)
                addedCount += 1
            
            messages(f"[OPTIMIZER] Loaded {addedCount} historical positions into learning database", 
                    console=1, log=1, telegram=0)
            return addedCount
            
        except Exception as e:
            messages(f"[OPTIMIZER] Error loading historical positions: {e}", console=0, log=1, telegram=0)
            return 0

    def getOptimizationStatus(self) -> Dict:
        """Get current optimization status"""
        total = self.learningDb["totalClosedPositions"]
        return {
            "totalPositions": total,
            "learningEnabled": self.learningDb.get("learningEnabled", True),
            "readyForOptimization": total >= self.minimumSampleSize,
            "nextOptimizationAt": self.minimumSampleSize if total < self.minimumSampleSize else 
                                  ((total // self.optimizationFrequency + 1) * self.optimizationFrequency),
            "lastOptimization": self.learningDb.get("lastOptimization"),
            "currentWinRate": self.calculateCurrentWinRate()
        }


# Global instance
optimizer = IntelligentParameterOptimizer()
