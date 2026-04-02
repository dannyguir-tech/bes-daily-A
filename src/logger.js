/**
 * logger.js — Winston logger with timestamp + level + message to console.
 */

import winston from 'winston';

const logger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(
    winston.format.timestamp({ format: 'YYYY-MM-DD HH:mm:ss' }),
    winston.format.printf(({ timestamp, level, message }) => {
      return `[${timestamp}] ${level.toUpperCase().padEnd(5)} ${message}`;
    })
  ),
  transports: [new winston.transports.Console()],
});

export default logger;
